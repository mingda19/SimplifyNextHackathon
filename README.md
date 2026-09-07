# Pantry — an agentic supply chain for charities

> Built for the SimplifyNext Agentic AI Hackathon 2026.

Pantry is an agentic backend and dashboard that senses stock levels, beneficiary feedback and
commodity prices, predicts where a charity's supply will fail next, and drafts the fix — a purchase
order or an acquisition checklist — for a human to approve before anything is committed.

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

Pantry handles **two archetypes**, because their failure modes are opposite:

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

The orchestrator runs a four-phase LangGraph loop:

1. **Sense** — pulls live inventory, lot expiries, open orders, beneficiary unmet-needs and the price
   forecast into one State-of-the-World snapshot. Degrades gracefully if an upstream service is down.
2. **Predict** — an LLM reasons over that snapshot against fixed baselines (minimum days of cover,
   monthly budget, expiry buffer) and forecasts what fails next and when.
3. **Act & adapt** — executes the plan against the inventory service. On a `4xx` (out of stock, MOQ
   not met, lead time exceeded, expired lot), it feeds the error and its `alternatives` back into
   reasoning and retries with a revised step, up to 3 times, instead of crashing.
4. **Human approval** — a LangGraph `interrupt()` pauses before anything commits. The dashboard shows
   what it sensed, what it predicted, the queued actions, and every adaptation it made along the way.
   Only on approval does the graph resume and place the real order or issue the checklist.

## Architecture

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ Inventory   │   │ Feedback    │   │ Price       │
│ Service     │   │ Service     │   │ Forecaster  │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       │  Postgres       │  NLP            │  DSPI
       └─────────────────┼─────────────────┘
                         ▼
            ┌────────────────────────┐
            │  Orchestrator          │
            │  LangGraph             │
            │  sense→predict→act→⏸   │
            └────────────┬───────────┘
                         ▼
                 Approval dashboard
```

## Services

| Service | Port | Responsibility |
|---|---|---|
| `services/inventory` | 8000 | System of record: items, lots, vendors, orders. Postgres + FastAPI. Returns typed `{code, message, remedy_hint, alternatives}` errors so the agent can adapt instead of guessing. |
| `services/auth` | 8001 | Charity and recipient accounts, request links, JWT issuing. |
| `services/feedback` | 8002 | Captures beneficiary feedback, extracts structured unmet needs via Claude, joins them to real SKUs. |
| `services/orchestrator` | 8003 | The LangGraph agent: sense → predict → act/adapt → approval → commit. `SqliteSaver` checkpointing so a pending approval survives a restart. |
| `services/price_forecaster` | 8004 | Trend/seasonality signal (`BUY_NOW` / `DEFER` / `NEUTRAL`) from the DSPI commodity index, with confidence and data-lag attached — never a claim of day-level precision. |
| `postgres` | 5432 | Shared Postgres 16. One instance, one schema per service (`inventory`, `auth`, `feedback`) so services stay isolated without a second container. Bound to `127.0.0.1` only; override with `POSTGRES_PORT`. |
| `frontend/legacy-app` | 5173 | React 19 + Vite dev server (`npm run dev` in `frontend/legacy-app`). The charity dashboard and the public recipient link. Not containerised — run it on the host against the compose stack. |

Two fields carry the integration across services — do not drop them: `items.dspi_series` (SKU → DSPI
commodity row, used for pricing) and `lots.source` (`PURCHASED` vs `DONATED`, the Type A/B signal).

Baselines the agent reasons against (`pantry_common/baselines.py`):

```python
BASELINES = {
    "min_days_cover": 10,
    "monthly_budget_sgd": 5_000,
    "max_single_order_sgd": 1_500,   # above this → mandatory approval
    "expiry_buffer_days": 14,
}
```

## Repo layout

```
services/inventory/       stock, lots, vendors, orders
services/auth/             accounts, roles, request links
services/feedback/         beneficiary feedback + extraction
services/orchestrator/     LangGraph agent
services/price_forecaster/ DSPI trend/seasonality signal
services/pantry_common/    shared auth + baseline helpers
frontend/legacy-app/               approval dashboard (React + Vite + TypeScript)
frontend/intake/            beneficiary feedback intake page
data/                        cached DSPI CSV and parsing scripts
scripts/                     setup, seeding, AWS SSO and readiness helpers
tests/                       cross-service contract and readiness tests
```

## Getting started

Requires Docker and Node.js 20.12+.

1. Generate the required auth secrets and create `.env` from the template:

   ```bash
   node scripts/setup_auth.mjs
   ```

   This fills in `AUTH_JWT_SECRET` and `SERVICE_AUTH_TOKEN` (two distinct random values of at least
   32 characters) and preserves any settings you've already customised. `FAKE_LLM=1` stays on by
   default so nothing calls Bedrock, and therefore costs money, until you turn it off deliberately.

2. Build and start every service:

   ```bash
   docker compose up --build -d
   ```

   This starts Postgres, bootstraps the auth/feedback/agent schemas, runs inventory migrations, and
   seeds demo data — including a default charity login, `Example@gmail.com` / `Example123`.

3. Run the dashboard:

   ```bash
   cd frontend/legacy-app
   npm ci
   npm run dev
   ```

   Sign in with the seeded account (or sign up your own) before using stock, feedback or agent
   actions — those routes require an authenticated charity session.

## Testing

```bash
PYTHONPATH=services/inventory:services python -m pytest services/inventory/tests -q
PYTHONPATH=services python -m pytest services/orchestrator/tests -q
PYTHONPATH=services/feedback:services python -m pytest services/feedback/tests -q
python scripts/test_readiness.py
```

The readiness runner spins up its own disposable Postgres container and exercises real HTTP/SQL
boundaries: concurrent orders and approvals, idempotent replay, role restrictions, receipts, and all
five adaptation error codes.
