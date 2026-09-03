# Pantry — an agentic supply chain for charities

> SimplifyNext Agentic AI Hackathon 2026 · Submission due **7 Sep 2026**

## Problem statement

> Change is everywhere — in how we live, learn and relate to one another. Transformation takes time,
> effort, and the right support at the right moment.
>
> This is your chance to build something that helps. We envision a solution that plans, acts, and
> adapts over time.
>
> Your team will choose a problem and decide who it serves. You will design a solution that thinks
> ahead, takes action, and leaves people genuinely better off.

## Who it serves

Charities running supply operations for beneficiaries — food banks, community fridges, welfare homes.
They run lean, plan by spreadsheet, and find out they're short *after* someone has gone without.

We handle **two archetypes**, because their failure modes are opposite:

| | **Type A — Donation-fed** | **Type B — Budget-funded** |
|---|---|---|
| Supply source | Donated goods, unpredictable arrival | Purchased with donated money |
| Core problem | Can't control *what* arrives; waste from expiry, gaps in essentials | Fixed budget, prices move, buying at the wrong moment costs meals |
| Agent output | Prioritised **acquisition checklist** + flagged review items (expiry, over/under-stock) | **Draft purchase order**, timed against price trend, held for human approval |

Both share one engine. The difference is only the terminal action.

## What makes it agentic

Beneficiary feedback is the sensing input nobody else uses. "The rice ran out again," "my mother
can't chew the dried food" — free text from the people actually served, parsed into structured unmet
needs, joined against live stock, and used to *reprioritise what gets acquired next*. The loop closes
from the beneficiary back to the purchase order.

---

## The universal 4-step agentic flow

### PHASE 1 · SENSE — the ingestion node
Continuously read external state and detect changes before they become crises.

- **Trigger** — scheduled timer, incoming webhook, or user prompt.
- **Tool Call 1 (Primary)** — live system status: current inventory, lot expiries, open orders.
- **Tool Call 2 (Context)** — external variables: commodity price index, weather, feedback backlog.
- **Output** — a unified *State of the World* JSON payload.

### PHASE 2 · PREDICT — the reasoning node
Use LLM reasoning to identify upcoming friction and formulate a mitigation plan.

- **Analysis** — compare State of the World against baseline rules (min days cover, budget ceiling,
  expiry buffer).
- **Forecasting** — project the timeline: *"based on X changing, Y fails in Z days."*
- **Planning** — generate a multi-step strategy and select which internal tools to use.
- **Output** — a structured plan (Action A, B, C) held in LangGraph state.

### PHASE 3 · ACT & ADAPT — the execution loop
Execute the plan, hit a roadblock, adapt without crashing.

- **Tool Call 3** — attempt step 1 (request a quote, place an order, reallocate stock).
- **Validation** — did the API return `200`, or an error?
- **The agentic loop** — on success, advance. On error (`OUT_OF_STOCK`, `MOQ_NOT_MET`,
  `LEAD_TIME_EXCEEDED`), the agent does **not** quit: it reads the error, feeds it back into
  reasoning, and selects an alternative vendor, quantity, or date.
- **Output** — a staged *Draft Resolution*, technically validated by the backend, held pending.

### PHASE 4 · HUMAN APPROVAL — the guardrail node
Ensure safety, budget control, and high-fidelity decisions.

- **The breakpoint** — LangGraph `interrupt()`. Execution pauses.
- **The handoff** — surface a natural-language summary: what it sensed, what it predicted would go
  wrong, the exact actions queued, **and every adaptation it had to make**.
- **Human input** — `[Approve]` / `[Reject]` / `[Modify]`.
- **Final execution** — on approval the graph resumes, commits the real calls, closes the ticket.

---

## Architecture

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ 1 Inventory │   │ 2 Feedback  │   │ 3 Price     │
│   Service   │   │   Service   │   │  Forecaster │
│   W · G     │   │   J · M     │   │     M       │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       │  Postgres       │  NLP            │  DSPI
       └─────────────────┼─────────────────┘
                         ▼
            ┌────────────────────────┐
            │  4  Orchestrator       │
            │     LangGraph · M · A  │
            │  SENSE→PREDICT→ACT→⏸   │
            └────────────┬───────────┘
                         ▼
                 Approval dashboard
```

**Contracts are frozen as written below.** Every workstream builds against these shapes from hour
one, using stubs where an upstream service isn't ready. Nobody blocks on anybody.

---

## Workstream 1 · Inventory Service — **W** and **G**

Postgres + FastAPI. The system of record, and the source of the errors that make Phase 3 interesting.

### Schema

```sql
items      (sku PK, name, category, unit, on_hand, reorder_point,
            avg_daily_draw, unit_cost_sgd, preferred_vendor_id,
            dspi_series)          -- joins to workstream 3
lots       (lot_id PK, sku FK, qty, expiry_date, received_at,
            source)               -- 'PURCHASED' | 'DONATED'  ← the A/B distinction
vendors    (vendor_id PK, name, moq_units, lead_time_days, reliability)
orders     (order_id PK, vendor_id FK, sku FK, qty, status,
            unit_price_sgd, placed_at, expected_at)
```

Two fields carry the whole integration — do not drop them:
- `items.dspi_series` maps a SKU to its DSPI commodity row (`"Rice"`, `"Vegetables, Fresh, Chilled,
  Frozen Or Simply Preserved"`). Without it, workstream 3 can't price anything.
- `lots.source` is what makes a charity Type A or Type B. Seed a realistic mix.

### Endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `/inventory` | `?category=&below_reorder=true` |
| `GET` | `/inventory/{sku}` | includes lots, days_cover |
| `POST` | `/inventory` | create |
| `PATCH` | `/inventory/{sku}` | update |
| `DELETE` | `/inventory/{sku}` | |
| `GET` | `/inventory/alerts` | expiring ≤14d, below reorder point, overstocked |
| `POST` | `/vendor/{id}/quote` | `{sku, qty}` → price + availability |
| `POST` | `/vendor/{id}/order` | commits — the call Phase 4 gates |

### Error codes — the deliverable, not a detail

The adaptation loop is where the rubric points are. These must fire **deterministically** so the demo
is reproducible:

| Code | Condition | Expected agent adaptation |
|---|---|---|
| `409 OUT_OF_STOCK` | vendor has none | fall back to secondary vendor |
| `400 MOQ_NOT_MET` | qty < `vendors.moq_units` | raise qty, or split across vendors |
| `422 LEAD_TIME_EXCEEDED` | `expected_at` after stockout date | re-plan, try faster vendor |
| `410 LOT_EXPIRED` | allocating from an expired lot | reallocate to a live lot |
| `429` + `Retry-After` | rate limit | back off and retry |

Every error body returns `{"code", "message", "remedy_hint", "alternatives": [...]}` — `alternatives`
is what lets the agent adapt intelligently instead of guessing.

### Actionables
- [ ] **W** — Docker Compose (Postgres + API), schema + migrations, seed script (~40 SKUs, mixed
      `source`, staggered expiries, ≥3 vendors with different MOQ and lead times)
- [ ] **W** — CRUD endpoints + `/inventory/alerts`
- [ ] **G** — vendor quote/order endpoints with the full error table above
- [ ] **G** — price-move hook: quotes drift with the DSPI index from workstream 3, so a retry lands
      on a genuinely different number
- [ ] **G** — `scripts/force_error.sh <code>` to trigger each error on demand for the demo
- [ ] **W** — OpenAPI spec published to `/docs` by **4 Sep**, so 2/3/4 can generate clients

---

## Workstream 2 · Feedback Service — **J** and **M**

Capture beneficiary feedback, extract structure, join it to stock.

### Endpoints

| Method | Path | Notes |
|---|---|---|
| `POST` | `/feedback` | `{beneficiary_id, text, lang, channel}` → runs extraction |
| `GET` | `/feedback` | `?since=&urgency=&category=` |
| `GET` | `/feedback/unmet-needs` | **aggregated — this is what the agent consumes** |

### Extraction contract

```json
{
  "sentiment": "negative",
  "urgency": 4,
  "categories": ["staples", "dietary_accessibility"],
  "mentioned_skus": ["RICE-5KG"],
  "unmet_needs": [
    {"need": "softer food for elderly", "confidence": 0.82, "suggested_category": "soft_foods"}
  ]
}
```

`mentioned_skus` is the join key — free text → real inventory row. That mapping is what makes the
whole system close its loop, so build it first and test it hardest.

### On "trained NLP model"
**Do not fine-tune from scratch.** In four days it will underperform and eat the schedule. Use:
1. **Structured extraction via Claude** with a strict JSON schema — best accuracy per hour, and it
   handles the messy multilingual reality of real beneficiary feedback.
2. A **pretrained** HuggingFace sentiment classifier (e.g. a DistilBERT SST-2 variant) running
   alongside, for the "trained model" story and as a cheap sanity check on the LLM's sentiment field.

That's a defensible hybrid. Fine-tuning is a stretch goal only if 1 and 2 land early.

### Actionables
- [ ] **J** — `POST /feedback` + Postgres table (share W's instance, separate schema)
- [ ] **J** — extraction pipeline to the contract above; log raw text *and* parsed output
- [ ] **J** — feedback intake frontend: large type, high contrast, minimal fields. This is where
      **UX & Design (15%)** is won or lost — the user is an elderly beneficiary, not an ops manager.
- [ ] **M** — `GET /feedback/unmet-needs` aggregation: rank unmet needs by frequency × urgency,
      resolve to SKUs, flag needs with **no matching SKU** (the highest-signal output — a gap nobody
      has stocked for)
- [ ] **J** — seed ~50 realistic feedback entries, deliberately including Singlish, a Mandarin
      entry, and two that map to no existing SKU
- [ ] *Stretch, only if ahead:* voice intake (Web Speech API) + translation

---

## Workstream 3 · Price Forecaster — **M**

Source data verified and documented in [DATA_SOURCES.md](DATA_SOURCES.md).
DSPI 3-digit monthly, `d_20e2fa37d1c8c19357a3f888487ab9f4`, 174 commodities, 1980 → Jun 2026.

### Scope — read this before building

The data is **monthly, published with a ~2–3 month lag**. It cannot answer "buy on Tuesday," and any
claim that it can will collapse under one judge's question. What it answers honestly:

- trend direction and magnitude over 3/6/12 months
- seasonality — is this commodity reliably cheaper in a given quarter?
- a **regime signal** the orchestrator can act on, with confidence and data-freshness attached

### Endpoint

```
GET /price/forecast?series=Rice&horizon_months=3
```
```json
{
  "series": "Rice",
  "as_of": "2026-06",
  "data_lag_months": 3,
  "latest_index": 95.706,
  "pct_change_3m": 2.15,
  "pct_change_12m": 4.02,
  "direction": "rising",
  "seasonal_low_months": ["Jan", "Feb"],
  "recommendation": "BUY_NOW",
  "confidence": 0.71,
  "rationale": "Rising 4 consecutive months (+2.15%); no seasonal trough due before Jan."
}
```

`data_lag_months` in the response is not defensive padding — it's the detail that makes the whole
system read as honest engineering rather than a demo.

### Actionables
- [ ] **M** — ingest DSPI to `data/dspi.csv`, cache locally (`poll-download` rate-limits at `429` —
      see DATA_SOURCES.md), **melt wide→long**: 631 month-columns, newest-first, quoted commas in
      labels, use a real CSV parser
- [ ] **M** — trend + seasonality (12-month rolling mean, month-of-year averages). Statsmodels
      seasonal decomposition if it's quick; a rolling mean is entirely sufficient and more explainable
- [ ] **M** — `BUY_NOW`/`DEFER`/`NEUTRAL` rule with an explicit, written-down threshold
- [ ] **M** — serve the endpoint; expose the SKU→`dspi_series` mapping W and G need
- [ ] **M** — one chart for the deck: index history with the recommendation window marked
- [ ] **Timebox: half a day.** When it serves the contract, stop and move to workstream 4.

---

## Workstream 4 · Orchestrator — **M**, joined by **A** on return

LangGraph. This is the submission. Everything above is infrastructure feeding this graph.

### Graph

```
sense ──► predict ──► act ──► [interrupt] ──► commit ──► END
             ▲         │
             └─ adapt ─┘   (on 4xx: re-reason, pick alternative, retry — max 3)
```

### Node contracts

- **`sense`** — parallel calls to `/inventory`, `/inventory/alerts`, `/feedback/unmet-needs`,
  `/price/forecast`. Emits one State-of-the-World object. Must degrade gracefully: if a service is
  down, note it in state and continue — do not crash the graph.
- **`predict`** — Claude reasons over State of the World against `BASELINES`. Emits a typed plan.
- **`act`** — executes plan steps against the inventory service. On 4xx, routes to `adapt`.
- **`adapt`** — feeds the error body (including `alternatives`) back to Claude, produces a revised
  step. Cap retries at 3, then escalate to human with the failure explained.
- **`interrupt`** — pause before any committing call.
- **`commit`** — on approval, place the order / emit the checklist.

### Baselines

```python
BASELINES = {
    "min_days_cover": 10,
    "monthly_budget_sgd": 5_000,
    "max_single_order_sgd": 1_500,   # above this → mandatory approval
    "expiry_buffer_days": 14,
}
```

### Two terminal actions

- **Type A (donation-fed)** → prioritised acquisition checklist + flagged review items, ranked by
  unmet-need urgency × days-cover shortfall.
- **Type B (budget-funded)** → draft PO with vendor, qty, price, and the timing rationale from
  workstream 3, held at `interrupt()` for approval.

### Actionables
- [ ] **M** — graph skeleton with all six nodes against **stubbed** services, by **4 Sep**. Do not
      wait for 1/2/3 to be real; this is the critical path.
- [ ] **M** — `SqliteSaver` checkpointing, **not** `MemorySaver`. A reload that preserves a pending
      approval is a production-grade signal in the video.
- [ ] **M** — the adapt loop, proven against every error code in workstream 1's table
- [ ] **A** — approval dashboard: what it sensed → predicted → queued → **adaptations made**. That
      last panel is the story of the build; give it the most space.
- [ ] **A** — reasoning trace view (collapsible per node)
- [ ] **M** + **A** — end-to-end demo scenario, scripted and rehearsed (below)

---

## The demo scenario

Scripted, deterministic, ~3 minutes. Rehearse it until it cannot fail.

1. Feedback arrives: three beneficiaries mention rice running out; one asks for softer food.
2. `sense` — rice at 8 days cover (below the 10-day baseline); DSPI shows rice rising 4 months.
3. `predict` — stockout in 8 days; lead time is 5; price trending up → order now, not next cycle.
   Softer-food need maps to **no existing SKU** → flagged for human.
4. `act` — orders 200kg from the preferred vendor → **`400 MOQ_NOT_MET`**.
5. `adapt` — reads `alternatives`, raises to the 250kg MOQ, re-prices → the second vendor is now
   cheaper → switches vendor.
6. `interrupt` — dashboard shows the sensing, the prediction, the queued PO, **and both adaptations**.
7. Human approves → order commits, ticket closes.

Step 5 is the moment that wins the room. Everything else is setup for it.

---

## Timeline

| Date | Milestone | Owner |
|---|---|---|
| **3 Sep** (today) | Contracts frozen · repo scaffolded · everyone unblocked | all |
| **4 Sep** | Services standalone against stubs · OpenAPI published · graph skeleton runs | all |
| **5 Sep** | **Integration day** — orchestrator calls real services end to end | all |
| **6 Sep AM** | **Feature freeze.** Only bug fixes after this point. | all |
| **6 Sep PM** | Demo rehearsed · video recorded · deck built · docs written | all |
| **7 Sep** | Buffer · **submit** | M |

Deliverables: documentation · prototype · solution video · pitch deck.

Judging: Innovation & Creativity 25% · Technical Excellence 25% · Impact & Business Value 25% ·
UX & Design 15% · Presentation & Demonstration 10%.

Presentation and UX together are **25%** — the same weight as Technical Excellence. The 6 Sep PM
block is not padding, and it is the first thing that will be tempting to sacrifice. Don't.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **A is unavailable and owns the dashboard** | **High** | M owns workstream 4 outright and builds a minimal approval UI on day 2. A's dashboard upgrades it on return; it is never the only version. |
| Integration slips past 5 Sep | High | Contracts frozen today; stubs from hour one; nobody waits on a real service |
| Fine-tuning an NLP model eats the schedule | Medium | Pretrained + LLM extraction only. Fine-tune is a stretch goal, not a dependency. |
| Overclaiming price precision | Medium | `data_lag_months` shipped in the response; "regime signal," never "optimal timestamp" |
| Live demo fails on stage | Medium | Scripted deterministic scenario + `force_error.sh` + a recorded fallback video |
| Scope creep (voice, translation) | Medium | Explicitly stretch. Nothing starts before 6 Sep freeze. |

## Repo layout

```
services/inventory/     W · G
services/feedback/      J · M
services/pricing/       M
orchestrator/           M · A
frontend/               J (intake) · A (approval dashboard)
data/                   cached DSPI CSV (gitignored)
scripts/                check_sources.sh, force_error.sh, seed.py
```

## Getting started

```bash
cp .env.example .env      # add ANTHROPIC_API_KEY
docker compose up -d      # Postgres + services
./scripts/check_sources.sh
```

See [DATA_SOURCES.md](DATA_SOURCES.md) for every verified external endpoint.
