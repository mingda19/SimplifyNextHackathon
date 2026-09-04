# Workstream 4 — Orchestrator Implementation Plan

Branch `func4/Orchestrator`. Owner **M**, **A** joining on return.
Consumes services 1/2/3 per the contracts in [../README.md](../README.md).

---

## 0. The two constraints that shape every decision

**Budget: US$20, hard.** Warning email near $12. At **$20 access is revoked**; at $30 the account is
terminated. The lease is **one-time and non-renewable** — a repeat request will not be approved if you
burn it. Cost reporting lags by hours, so the bar you see is optimistic; treat **$12 as the ceiling**
and the remaining $8 as reserve for demo day.

**Time: submission 7 Sep.** Feature freeze 6 Sep AM.

Everything below follows from those two.

---

## 1. What runs where — the central architecture decision

> **Postgres runs in Docker on our laptops. It never becomes RDS.**

The AWS deck lists EC2/RDS/always-on services under "if you're launching a server, stop and rethink,"
and a NAT Gateway alone is ~$1/day *idle*. Our stack is local except for model inference:

| Component | Where | Cost |
|---|---|---|
| Postgres (services 1 & 2) | local Docker | **$0** |
| FastAPI services 1/2/3 | local uvicorn | **$0** |
| LangGraph orchestrator | local Python | **$0** |
| SqliteSaver checkpoints | local file | **$0** |
| Approval dashboard | local Vite dev server | **$0** |
| **Claude inference** | **Amazon Bedrock, `us-east-1`** | **the only line item** |

**Do not deploy to Lambda/DynamoDB/S3 for the submission.** It is not required by the rubric, it costs
days we don't have, and a VPC misstep can eat the whole budget overnight. Bedrock *is* genuine AWS
usage. If we finish early, a read-only Lambda Function URL demo is a stretch goal on 6 Sep — never
before.

Region is **`us-east-1`**. Wrong region produces `Access denied to bedrock:ListFoundationModels`
errors that look like a permissions problem and aren't.

---

## 2. Cost model

Only **2 of the 6 nodes call a model.** `sense`, `act`, `interrupt` and `commit` are deterministic I/O
and cost nothing. That is a deliberate design choice, not an accident — see §4.

Rough per-run shape (worst case, 3 adaptation retries):

| Node | Calls | Input tok | Output tok |
|---|---|---|---|
| `predict` | 1 | ~4,000 | ~800 |
| `adapt` | ≤3 | ~5,000 ea | ~500 ea |
| **Total** | **≤4** | **~19,000** | **~2,300** |

At Claude Haiku 4.5 list rates ($1 / $5 per MTok) that's ≈ **$0.03 per full run** — call it **$0.05**
with slop. So ~240 runs inside a $12 ceiling.

> ⚠️ **Those are Anthropic first-party rates, used here as a planning proxy.** Bedrock is
> partner-operated and priced separately — check <https://aws.amazon.com/bedrock/pricing/> and correct
> this table on day 1. Also note **Message Batches is not available on Bedrock**, so there is no 50%
> batch discount to fall back on.

**The real risk is not the demo runs — it's the dev loop.** Two hundred careless `python -m
orchestrator` invocations while debugging graph plumbing will drain this faster than any demo. §7 is
the mitigation and it is not optional.

---

## 3. Model selection

Going with **Claude Haiku 4.5** as M proposed. Correct call: it's the cheapest current model, and 4 of
our 6 nodes don't touch a model at all, so the ceiling is low regardless.

```python
from anthropic import AnthropicBedrockMantle

client = AnthropicBedrockMantle(aws_region="us-east-1")

MODEL_PREDICT = os.getenv("MODEL_PREDICT", "anthropic.claude-haiku-4-5")
MODEL_ADAPT   = os.getenv("MODEL_ADAPT",   "anthropic.claude-haiku-4-5")
```

**Three traps, all of which will cost us an afternoon if we hit them cold:**

1. **Ignore the model ID in the AWS deck.** It shows `anthropic.claude-3-haiku-20240307-v1:0`, a
   2024-era model. Current Haiku on Bedrock is `anthropic.claude-haiku-4-5` — Bedrock IDs take the
   `anthropic.` prefix; the first-party ID is the bare `claude-haiku-4-5`. Never append date suffixes.
2. **Use `AnthropicBedrockMantle`, not `AnthropicBedrock`.** The latter is the legacy
   `bedrock-runtime` InvokeModel path. The legacy integration also rejects top-level `cache_control`
   with a 400 — another reason to stay on Mantle.
3. **Haiku 4.5 is a pre-4.6 model, so the modern knobs are absent.** `output_config: {effort: ...}`
   **errors** on it. Extended thinking, if we ever want it, is the old
   `thinking={"type": "enabled", "budget_tokens": N}` form (N ≥ 1024, < `max_tokens`) — *not*
   `{"type": "adaptive"}`. Simplest path: **don't enable thinking on Haiku at all**; our prompts are
   short and structured.

**Split-model escape hatch.** `adapt` is the genuinely reasoning-heavy node — it reads an HTTP error
body and re-plans. If Haiku produces weak adaptations, flip **only that node** to
`anthropic.claude-sonnet-5` via the env var above. Roughly 2× the per-token cost on ~30% of our
calls — affordable, and it keeps `predict` cheap. Decide this with evidence on 5 Sep, not by guessing
now.

**`max_tokens` is a safety ceiling, not a charge** — we're billed for tokens actually generated. Set
it low anyway so a runaway generation can't cost us: `predict` 4096, `adapt` 2048.

---

## 4. The six nodes

```
sense ──► predict ──► act ──► [interrupt] ──► commit ──► END
             ▲         │
             └─ adapt ─┘        max 3 retries, then escalate
```

### 4.1 `sense` — ingestion · **no LLM** · $0

Reads the world. Deterministic on purpose: making a model do data fetching is the most common way
hackathon agents waste money, and it adds a failure mode for zero benefit.

**Infra:** four parallel HTTP calls to local services — `GET /inventory`, `GET /inventory/alerts`,
`GET /feedback/unmet-needs`, `GET /price/forecast`. Use `asyncio.gather` + `httpx`.

**Must degrade, never crash.** A teammate's service will be down at some point on 5 Sep. Wrap each
call; on failure record `{"service": "pricing", "status": "unavailable"}` in state and continue. The
`predict` prompt then explicitly says which inputs were missing, and the agent reasons without them.
Showing that in the video is a feature, not an apology.

**Output:** one `StateOfWorld` object. Serialize with `json.dumps(..., sort_keys=True)` — unsorted
keys silently break prompt caching (§7).

### 4.2 `predict` — reasoning · **LLM call #1** · ~$0.01

Compares `StateOfWorld` against `BASELINES`, forecasts the failure, emits a typed plan.

**Use structured outputs — Bedrock supports them.** Do not parse free text.

```python
from pydantic import BaseModel
from typing import Literal

class PlanStep(BaseModel):
    action: Literal["request_quote", "place_order", "reallocate_lot", "flag_for_human"]
    sku: str
    qty: int
    vendor_id: str | None
    rationale: str

class Plan(BaseModel):
    stockout_sku: str
    days_until_failure: int
    reasoning: str
    steps: list[PlanStep]

resp = client.messages.parse(
    model=MODEL_PREDICT,
    max_tokens=4096,
    system=[{"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}}],   # explicit breakpoint — §7
    messages=[{"role": "user", "content": state_json}],
    output_format=Plan,
)
plan = resp.parsed_output      # a validated Plan
```

`Literal[...]` on `action` matters: it constrains the model to actions `act` can actually execute, so
a hallucinated verb becomes a validation error instead of a runtime crash mid-demo.

**Baselines live in code, not in the prompt's prose** — Phase 4 reads them back to the human, so they
must be one source of truth:

```python
BASELINES = {"min_days_cover": 10, "monthly_budget_sgd": 5_000,
             "max_single_order_sgd": 1_500, "expiry_buffer_days": 14}
```

### 4.3 `act` — execution · **no LLM** · $0

Executes `plan.steps[i]` against the inventory service. Pure dispatch — a dict mapping `action` →
function. No model call: the plan is already typed, so there is nothing left to reason about.

**Routing:** `200` → next step. `4xx` → `adapt`. `5xx`/timeout → retry twice with backoff, then
`adapt` with the transport error as context.

Records every attempt into `state["attempts"]` — this list is what the dashboard renders as the
adaptation trail, and it's the most valuable artifact the graph produces.

### 4.4 `adapt` — the agentic loop · **LLM calls #2–4** · ~$0.01 each

**This node is the submission.** Everything else is scaffolding around it.

Receives the failed step plus the error body from workstream 1:
`{"code", "message", "remedy_hint", "alternatives": [...]}`. Returns a revised `PlanStep`.

```python
class Adaptation(BaseModel):
    revised_step: PlanStep
    what_changed: str      # human-readable — goes straight to the dashboard
    confidence: float
```

**Hard retry cap of 3**, tracked in `state["retry_count"]`. On exhaustion, route to `interrupt` with
an explicit "I could not resolve this" summary rather than looping. An uncapped adapt loop is the one
bug in this design that can actually cost real money — a wedged graph calling Bedrock forever is how
a $20 budget disappears while you're at dinner. Cap it before you write anything else in this node.

**Feed `alternatives` in explicitly.** The difference between an agent that reasons and one that
guesses is whether it was given the option set. This is why W and G must return that field.

### 4.5 `interrupt` — the guardrail · **no LLM** · $0

```python
from langgraph.checkpoint.sqlite import SqliteSaver
graph = builder.compile(checkpointer=SqliteSaver.from_conn_string("checkpoints.db"))
```

**`SqliteSaver`, never `MemorySaver`.** A reload that preserves a pending approval is the detail that
makes this read as production-grade in the video. (If we ever do deploy to Lambda, note its filesystem
is ephemeral — `/tmp` does not survive cold starts, so the checkpointer would have to move. Another
reason to stay local.)

Fires whenever the queued action commits money, or exceeds `max_single_order_sgd`. Emits the
four-panel payload: **sensed → predicted → queued → adaptations made**. That fourth panel is the story.

### 4.6 `commit` — execution · **no LLM** · $0

On approve, executes the real call and closes the ticket. Two terminal shapes:

- **Type A (donation-fed)** → ranked acquisition checklist + flagged review items.
- **Type B (budget-funded)** → `POST /vendor/{id}/order`, with the timing rationale from service 3.

Must be **idempotent** — an approval double-click cannot place two orders. Key on
`state["thread_id"] + step_index`.

---

## 5. Graph state

```python
class AgentState(TypedDict):
    thread_id: str
    state_of_world: dict
    degraded_services: list[str]
    plan: Plan | None
    current_step: int
    attempts: list[dict]        # every try + error + adaptation → the dashboard trail
    retry_count: int
    approval: Literal["pending", "approved", "rejected"] | None
    token_ledger: dict          # §7
```

---

## 6. Credentials & ops

**Access keys expire every 12 hours.** This will break a long build session, and it will break the
demo if we're careless.

- Keys go in `orchestrator/.env` (already gitignored — the `gitignore`→`.gitignore` rename landed on
  `main`). Load with `python-dotenv`.
- All three of `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, **and `AWS_SESSION_TOKEN`** are required.
  Omitting the session token is the classic first-hour failure with temporary credentials.
- Add `make creds` printing the refresh steps, and have the orchestrator fail fast with a clear
  "credentials expired, re-login at the access portal" message rather than an opaque SDK stack trace.
- **Record the demo video on 6 Sep**, not 7 Sep. Expired creds on submission morning with no recording
  is an avoidable way to lose.

The group representative shares username, password **and the 2FA secret string** so every member can
log in independently.

---

## 7. Cost controls — build these first, not last

**7.1 `FAKE_LLM=1` — the single highest-value control.** Nodes `sense`, `act`, `interrupt` and
`commit` are 4 of our 6, and none needs a model. Behind one env var, `predict` and `adapt` return
canned `Plan` / `Adaptation` fixtures. The entire graph — routing, retries, checkpointing, the
approval round-trip, the dashboard — is then developable and testable for **$0**. Expect ~80% of our
iteration to run this way. **Write the fixtures before the real calls.**

**7.2 Token ledger with a hard stop.** Accumulate `response.usage` after every call; persist to
`orchestrator/spend.json`; refuse to make a call once the session exceeds a configured cap.

```python
u = resp.usage
ledger["input"]  += u.input_tokens
ledger["output"] += u.output_tokens
ledger["cache_read"] += getattr(u, "cache_read_input_tokens", 0)
```

Because reported AWS spend lags by hours, this local ledger is our *only* real-time view. It also
demos beautifully — an agent that watches its own budget, in a project about budget guardrails.

**7.3 Prompt caching — with honest expectations.** Our system prompt and tool definitions are stable
across every call, so mark an explicit breakpoint on the system block (shown in §4.2). Cache reads
run ~0.1× cost.

Two caveats, so nobody is surprised:
- **Default TTL is 5 minutes.** Sporadic dev runs will mostly *miss*. This is a demo-day and
  tight-loop optimization, not a dev-cost saver.
- **Minimum cacheable prefix is model-dependent (512–4096 tokens)** and short prefixes silently fail
  to cache. Verify with `usage.cache_read_input_tokens` — if it's zero across repeated identical
  runs, something is invalidating it. Usual culprits: a timestamp or UUID in the system prompt, or
  unsorted `json.dumps()`. Hence `sort_keys=True` in §4.1.

**7.4 Never leave a loop running unattended.** See the retry cap in §4.4.

---

## 8. Build order

| When | Deliverable | Gate |
|---|---|---|
| **3 Sep PM** | Repo scaffold, `AgentState`, all 6 nodes as stubs, graph compiles and routes end to end under `FAKE_LLM=1` | graph runs, $0 spent |
| **4 Sep AM** | `sense` against real services (stub any that aren't up); `SqliteSaver` + `interrupt` round-trip | approval survives a restart |
| **4 Sep PM** | **First real Bedrock call.** `predict` with structured output. Ledger live. | one clean `Plan`, cost recorded |
| **5 Sep AM** | `adapt` against every error code in W/G's table; retry cap enforced | all 5 codes adapt correctly |
| **5 Sep PM** | **Integration** — real services, both terminal actions; minimal approval UI | full scenario passes |
| **6 Sep AM** | Freeze. A's dashboard upgrades the UI. Rehearse. | — |
| **6 Sep PM** | **Record video.** Deck, docs. | submitted artifacts exist |

Note 3 Sep PM: the entire graph exists and runs before a single cent is spent. That ordering is the plan.

---

## 9. Testing

- **Unit, `FAKE_LLM=1`:** every routing path — success, each 4xx → adapt, retry exhaustion → escalate,
  approve, reject. Free, so run them constantly.
- **Contract:** assert W/G's error bodies always carry `alternatives`. If that field is missing,
  `adapt` degrades to guessing and the demo's key beat dies.
- **Golden run:** the scripted README scenario, asserted end to end, deterministic via
  `scripts/force_error.sh MOQ_NOT_MET`.
- **Cost regression:** fail CI if a single golden run exceeds a token threshold — catches a prompt
  edit that accidentally 10×s our spend.

---

## 10. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Uncapped adapt loop drains the budget** | **High** | Hard cap of 3 in `state["retry_count"]`, written before the node's logic; local ledger with a hard stop |
| Dev iteration burns budget | High | `FAKE_LLM=1` fixtures built first; ~80% of runs never call Bedrock |
| Someone provisions RDS/NAT/OpenSearch | High | Postgres is local, full stop. Nothing in AWS but Bedrock. Say it in standup. |
| 12h credential expiry kills the demo | Medium | `make creds`, fail-fast error, **video recorded 6 Sep** |
| Haiku adapts weakly | Medium | Per-node model env var; flip `adapt` to Sonnet 5 on evidence, 5 Sep |
| Bedrock pricing ≠ assumed | Medium | Verify against AWS pricing page day 1; ledger tracks tokens regardless |
| Wrong region → opaque access-denied | Low | Pin `us-east-1` in `.env.example`; assert at startup |
| A unavailable, dashboard unbuilt | Medium | M ships a minimal approval UI on 4 Sep; A's version is an upgrade, never the only one |

---

## 11. Open question for the team

W and G need to confirm the error body always includes `alternatives` — `adapt` is built on it, and
without it the agent guesses instead of reasoning. Raise this at the next sync before they finalize
the vendor endpoints.
