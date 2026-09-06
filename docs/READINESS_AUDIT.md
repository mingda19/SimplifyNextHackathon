# Readiness audit — 6 September 2026

**Verdict: the services have working happy paths, but the integrated project is not ready for a real Workstream 4 demo.** Login works through Vite. The most serious failure is that the existing graph places real orders before human approval, including for donation-fed charities; rejecting the plan does not undo those orders.

Reviewed branch: `fix/frontend`, commit `b2f97f4`. This audit adds tests and a runner; it does not fix application behavior. A failing test is an outstanding finding, not an expected-failure marker.

## What was exercised

| Check | Result |
|---|---|
| Existing inventory suite | **36 passed** |
| Existing orchestrator suite | **20 passed**, using fake services/model |
| Existing feedback matcher suite | **1 passed**, containing **41 golden cases** |
| New readiness suite | **27 passed, 31 failed; 58 cases, no skips or setup errors** |
| Frontend production build | **Passed**, Vite 5.4.21; 45 modules transformed |
| Real Vite signup → login → authenticated `/me` | **201 → 200 → 200** |
| Vite inventory, feedback, agent reads | **200** |
| Vite pricing forecast | **404**, despite the pricing service being healthy separately |
| Real XGBoost forecast API | **26 forecasts passed** contract/finite-value checks; invalid series/horizons rejected |
| Concurrent purchase against the last 250 vendor units | **One 200, one 409; remaining availability 0** |
| Inventory's five deterministic errors | Correct 400/409/422/410/429 codes, bodies and alternatives; delayed 429 retry succeeded |
| Graph error delivery/retry cap | Injected all five errors; each reached adapt with its body intact, called adaptation three times, then paused for escalation |

The 31 failures represent multiple parameterized cases for the findings below, not 31 unrelated bugs. Across the existing and new pytest suites: **84 passed, 31 failed**.

Tests used Python 3.11.2, a disposable PostgreSQL 16 container, real HTTP processes for all five services, and temporary source copies. The copies protect tracked catalogue caches and graph checkpoint files. Test data and credentials were synthetic. Service addresses and schemas were supplied explicitly by the harness; this does **not** establish that the existing Compose configuration starts a complete integrated stack.

`FAKE_LLM=1` was forced. Actual XGBoost inference ran; Claude/Bedrock calls and the optional HuggingFace classifier were not exercised. The classifier's unavailable-dependency fallback ran. Visual browser automation was unavailable; the frontend was built and its actual Vite HTTP proxy tested, but rendering, clicks, mobile layouts, and accessibility remain unverified.

## Confirmed failures, in repair order

| Priority | Finding and evidence | Where to change |
|---|---|---|
| **P0** | **Orders commit before approval.** A live graph run created one database order before `interrupt()` for **both Type A and Type B**. A rejected run still left its order. Even `request_quote` created an order. `act` dispatches both actions to `vendor_order`, whose live implementation posts to `/order`. | `services/orchestrator/nodes/act.py:54`; `services/orchestrator/services.py:143` |
| **P0** | **The approval endpoint is not authenticated.** An anonymous caller resumed a pending graph using `decided_by: forged@example.org`; it returned 200. Anonymous callers also read inventory, beneficiary feedback and runs, and created an inventory item (201). The auth service's recipient restriction works on its own endpoints, but does not protect the other services. | `services/orchestrator/api.py:135`; inventory/feedback routers; shared service authorization |
| **P1** | **`commit` does not place an order.** Given a successfully quoted, staged PO and approval, calling `commit` added zero database orders. It only fabricates `status: CONFIRMED`. Changing `act` to use `/quote` must be accompanied by a real committing call here. | `services/orchestrator/nodes/commit.py:38` |
| **P1** | **The approval screen understates spending.** A real quote totals **S$562.50**, but the summary reports **S$0**. Real quotes use `total_price_sgd`; fixtures and summaries use `total_sgd`. Real order responses do not contain either total, requiring quantity × unit price. The single-order warning inherits the wrong value. | `services/orchestrator/nodes/approval.py:36`; `nodes/commit.py:64`; service adapter |
| **P1** | **Pricing is routed to the wrong service.** `/api/pricing/price/forecast?series=Rice` returns 404 through the unchanged Vite proxy. Pricing and agent share target port 8003, which Compose assigns to the orchestrator. No price forecaster service exists in Compose. | `frontend/app/vite.config.js:32`; `compose.yaml` |
| **P1** | **Compose does not connect the graph to live services.** It supplies only app/database settings; `FAKE_SERVICES` defaults to 1. Turning fake mode off also requires container DNS addresses: the defaults use `localhost`, which points to each container itself. Feedback's inventory URL is likewise unset. | `compose.yaml:74`; `services/orchestrator/config.py:34`; feedback configuration |
| **P1** | **Pending approval is not durable across container replacement.** `SqliteSaver` exists and the existing test proves a new graph instance can resume the same file. Compose mounts no volume for the orchestrator checkpoint. A rebuild/replacement does not preserve that writable container layer. | `compose.yaml:74`; `services/orchestrator/config.py:67` |
| **P1** | **Received stock cannot be issued.** The Incoming UI sends a PATCH to `on_hand`. Replaying that request created 10 units of on-hand stock with **zero lots**. Outgoing operations require a lot ID; no receipt/lot creation endpoint exists. Expiry/source information is also missing. | `frontend/app/src/pages/Stock.jsx:240`; inventory receipt contract |
| **P1** | **The live-model dependency set is incomplete.** Installing the declared inventory/auth/orchestrator dependencies leaves `boto3` and `botocore` absent. The installed `AnthropicBedrock` request-signing code imports them. Constructor creation alone succeeds, so it is not an adequate model readiness test. | Python requirements; use the SDK's Bedrock dependency extra or explicitly supply its dependencies |
| **P2** | **Stock inputs can crash the API.** `on_hand=2147483648` and a 100-digit integer return **500**, since the API permits values outside PostgreSQL INTEGER's range. `on_hand=true` is silently accepted as 1. Negative, fractional and blank-name inputs were correctly rejected. | `services/inventory/app/schemas.py:42` |
| **P2** | **Reserved SKU collision.** Creating SKU `alerts` succeeds, but GET `/inventory/alerts` is the alert collection route, not that item's detail route. Reject reserved/unaddressable identifiers or change route design. | `services/inventory/app/schemas.py:18`; inventory routes |
| **P2** | **The typed plan permits non-executable steps.** Negative/zero purchase quantities, purchase without vendor, and lot reallocation without a lot identifier all validate. `PlanStep` does not even carry a lot ID. `reallocate_lot` currently stages a stub, so the real LOT_EXPIRED adaptation path is not integrated. | `services/orchestrator/state.py:18`; `nodes/act.py:59` |
| **P2** | **Retry timing is lost.** The vendor client drops the `Retry-After` header. A simulated 429 with `Retry-After: 7` reaches the exception without that timing information. Adapt has no deterministic backoff path; repeated attempts can exhaust the cap before recovery. | `services/orchestrator/services.py:143`; `nodes/adapt.py` |
| **P2** | **Blank feedback is accepted.** Empty and whitespace-only text return 202 and enter extraction. This can create irrelevant records and, in real model mode, unnecessary inference calls. | `services/feedback/app/main.py:44` |
| **P2** | **Negative run-list limit returns 500.** `/agent/runs?limit=-1` passes straight to PostgreSQL LIMIT. | `services/orchestrator/api.py:116` |
| **P2** | **Calibration metadata describes a different gate.** The active gate is 0.60, with magnitude threshold 0.00314495. Stored realized validation/test statistics use magnitude threshold 0.00816236, corresponding to 0.70, but the API labels them `*_at_gate`. Forecast values themselves passed the API tests. | `services/price_forecaster/forecast.py:147`; `artifacts/calibration.json` |
| **P3** | **Revoked links still increment usage.** Resolving a revoked link correctly returns 404, but POST to its `/used` route returns 200 and updates it. | `services/auth/app/main.py:232` |

## Additional source-review findings

These were found in source/configuration; they are separate from the 58 executed readiness cases.

- **Commit replay and concurrent approvals:** `_COMMITTED` is a process-local set, loses state on restart, and is updated before work finishes. The decision API reads pending status and resumes in separate operations, without an atomic claim. Inventory order creation has no idempotency key. Durable idempotency is required before implementing a real post-approval commit and retrying ambiguous timeouts.
- **Monthly budget is prompt context, not an enforced spending control.** There is no accumulated monthly purchasing ledger, reservation check, or post-adaptation budget validation. The existing model-cost ledger measures USD inference expenditure, not SGD procurement. The single-order warning also compares a summed plan value to the single-order cap.
- **Type A output is not ranked by urgency × cover shortfall.** The current commit implementation iterates staged entries, including review flags in checklist items. The dashboard always starts Type B. This is unfinished Workstream 4 behavior.
- **Reasoning trace/Modify controls are unfinished.** The dashboard has four summary sections and adaptation cards, but no collapsible per-node trace and no Modify/resume workflow. An escalated plan still offers Approve.
- **A predict failure can appear approved.** `_run_graph` labels any graph result without `__interrupt__` as approved, including a predict halt; inspect `halt_reason` before interpreting this as 'nothing to approve'.
- **Deployment paths disagree.** `scripts/run_stack.sh` uses auth 8004, pricing 8003 and agent 8005; Vite/Compose use auth 8001 and agent 8003. Pick one documented mapping. Auth/feedback/agent schemas are mounted only under Postgres initialization scripts; existing database volumes need a schema migration/bootstrap step when upgrading from inventory-only deployment.
- **Auth's default signing secret is known.** `AUTH_JWT_SECRET` defaults to `dev-only-change-me`, and Compose does not pass a configured signing secret. Complete this configuration together with enforcing backend role checks.
- **Catalogue updates do not refresh the matcher.** `SKU_CATALOGUE`/`SKU_BY_CODE` are constructed on module import. A TTL in `catalogue.load_items()` does not automatically rebuild those tables. Without a cache, an inventory outage at import raises before feedback intake can start; a missing seeded alias target can also abort import.
- **Shared request links collapse multiple people into one identity.** The UI uses `LINK-${token}` as every anonymous sender's beneficiary ID. Aggregation deliberately counts distinct beneficiary IDs, so several people using one shared link count as one person. The same identity can be supplied directly to the unauthenticated feedback endpoint. Decide how anonymous participation should be measured.
- **Display name differs across login/reload.** Login returns `display_name`; `/auth/me` returns token claims with `name`; the sidebar reads `user.name`. This predicts a missing sidebar name until reload, but was not visually verified.
- **Tracked runtime artifacts:** `services/orchestrator/checkpoints.db-wal` and `checkpoints.db-shm` are tracked without the base checkpoint DB. They should not be packaged as application source. The audit left them untouched.
- **Frontend dependency audit:** npm reported **4 affected packages: 1 high, 3 moderate**, including Vite/Windows development-server advisories. This is the package audit's report, not an exploit test. Review the saved npm report before upgrading; no automatic force upgrade was performed.

## Workstream 4 acceptance status

| Requirement | Current status |
|---|---|
| Six-node LangGraph skeleton | Present |
| Parallel sensing and service-outage degradation | Present; existing outage tests pass |
| Claude structured plan | Fake path passes; live inference not verified; signing dependencies missing in declared install |
| All actions validated before approval | **Fails:** quotes and purchases commit early; reallocation is a stub |
| Adapt receives error and alternatives, capped at 3 | Injected-code routing/cap passes; real 429 backoff and lot dispatch unfinished |
| Pause before any committing call | **Fails against real inventory** |
| SqliteSaver/reload persistence | File-level resume test passes; container persistence and commit replay protection unfinished |
| Type A ranked checklist | Partial; real mode currently buys before approval |
| Type B correct draft PO held for approval | **Fails:** premature order, incorrect total, stub commit |
| Dashboard adaptation history | Present as summary cards; node traces/Modify/Type A selection unfinished |
| Deterministic rice demo | Fixture graph passes; live-integrated demo is **not ready** |

The next implementation should first separate quote/stage from commit, enforce authenticated approval and durable order idempotency, then fix money/stock contracts and deployment wiring. Those changes turn the current fake demo into a safe real-service demonstration. Keep these readiness tests as the acceptance checks while implementing that work.

## Reproduce

Start Docker Desktop. From the repository root on Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests/readiness/requirements.txt
.\.venv\Scripts\python.exe scripts/test_readiness.py
```

The runner creates a fresh container on an automatically assigned loopback port, applies schemas/migrations in that disposable database, runs the tests, and stops its container even when tests fail. Exit status 1 is currently expected because the assertions expose outstanding defects. It writes `.qa/readiness.log` and `.qa/readiness.xml`. It does not use the project's normal database or paid model APIs.

Existing suites are separate because inventory/auth/feedback each use a top-level Python package named `app`:

```powershell
Push-Location services/inventory
..\..\.venv\Scripts\python.exe -m pytest -q
Pop-Location

Push-Location services/feedback
$env:FAKE_LLM = '1'
$env:INVENTORY_URL = 'http://127.0.0.1:9'  # exercise the tracked catalogue cache
..\..\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
Remove-Item Env:INVENTORY_URL

$env:PYTHONPATH = 'services'
$env:FAKE_LLM = '1'
.\.venv\Scripts\python.exe -m pytest services/orchestrator/tests -q
Remove-Item Env:PYTHONPATH
```

Do not use the root `test.py` as an offline test command: it executes a real Bedrock request at module scope. Full Docker image builds, live extraction accuracy, model retraining/held-out scoring, sustained load and visual browser testing remain outside the verified results above.
