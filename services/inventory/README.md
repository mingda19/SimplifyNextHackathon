# Inventory Service

Workstream 1 is a local FastAPI + PostgreSQL inventory system of record. It
implements the frozen inventory, lot, vendor, and order contracts from the root
README, plus the approved minimal lot-allocation endpoint.

Authentication is intentionally omitted for this internal hackathon prototype.

## Run with Docker Compose

From the repository root:

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
curl http://localhost:8000/health
```

Compose waits for PostgreSQL, applies Alembic migrations, inserts any missing
demo fixtures, and then starts the API. Operational changes are not overwritten
when the container restarts.

- Swagger UI: <http://localhost:8000/docs>
- OpenAPI JSON: <http://localhost:8000/openapi.json>

Stop the stack without deleting its database volume:

```bash
docker compose down
```

## Migrations and seed data

```bash
docker compose exec inventory alembic current
docker compose exec inventory alembic upgrade head
docker compose exec inventory python -m app.seed
```

The ordinary seed command is idempotent and preserves operational changes. To
restore the deterministic demo from scratch, explicitly reset it:

```bash
docker compose exec inventory python -m app.seed --reset
```

The fixtures contain 40 SKUs, 80 staggered lots with both `PURCHASED` and
`DONATED` sources, four vendors, and private vendor/SKU offers. An explicit
reset resolves expiry dates relative to that day's UTC date, so the demo can be
re-anchored whenever needed.

## Public endpoints

```text
GET    /inventory
GET    /inventory/{sku}
POST   /inventory
PATCH  /inventory/{sku}
DELETE /inventory/{sku}
GET    /inventory/alerts
POST   /inventory/{sku}/allocate
POST   /vendor/{id}/quote
POST   /vendor/{id}/order
```

`GET /inventory` accepts `category` and `below_reorder=true`. Item details add
only `lots` and `days_cover`. When average daily draw is zero, `days_cover` is
`null`. Overstock means strictly more than 30 days of cover.

`POST /vendor/{id}/quote` is non-mutating and is suitable for pre-approval
validation. `POST /vendor/{id}/order` revalidates, creates a `PLACED` order, and
reserves vendor availability; the future orchestrator is responsible for only
calling it after human approval.

## Local pricing

There are no DSPI calls in Workstream 1. `items.dspi_series` is stored unchanged
for later integration. Quotes currently use an isolated deterministic formula:

```text
unit price = unit_cost_sgd × vendor multiplier × applicable quantity discount
total      = rounded unit price × quantity
```

All SGD values use decimal half-up rounding to cents. The implementation seam is
`app/services/pricing.py`, which Workstream 3 can replace later.

## Deterministic errors

Every domain error has exactly `code`, `message`, `remedy_hint`, and
`alternatives`. Trigger each scenario from the repository root after resetting
the seed:

```bash
bash scripts/force_error.sh OUT_OF_STOCK
bash scripts/force_error.sh MOQ_NOT_MET
bash scripts/force_error.sh LEAD_TIME_EXCEEDED
bash scripts/force_error.sh LOT_EXPIRED
bash scripts/force_error.sh RATE_LIMIT
```

Set `INVENTORY_URL` to target a non-default API origin. The rate-limit scenario
uses a process-local demo key, returns `Retry-After: 1`, verifies the delayed
retry, and automatically re-arms for repeated script runs.

## Seeded rice demo

Reset first so earlier allocations or orders cannot affect the result:

```bash
docker compose exec inventory python -m app.seed --reset
curl http://localhost:8000/inventory/RICE-5KG
curl -X POST http://localhost:8000/vendor/VENDOR-HARVEST/quote -H "Content-Type: application/json" -d '{"sku":"RICE-5KG","qty":200}'
curl -X POST http://localhost:8000/vendor/VENDOR-HARVEST/quote -H "Content-Type: application/json" -d '{"sku":"RICE-5KG","qty":250}'
curl -X POST http://localhost:8000/vendor/VENDOR-COMMUNITY/quote -H "Content-Type: application/json" -d '{"sku":"RICE-5KG","qty":250}'
curl -X POST http://localhost:8000/vendor/VENDOR-COMMUNITY/order -H "Content-Type: application/json" -d '{"sku":"RICE-5KG","qty":250}'
```

Rice starts with eight days of cover. The first quote fails because Harvest's
MOQ is 250. At 250 units, Community's deterministic bulk quote is SGD 2.25 per
unit versus Harvest's SGD 2.40, so the caller can switch vendors before the
committing order.

## Tests

The container contains the test dependencies and suite:

```bash
docker compose exec inventory pytest -q
```

For a host Python workflow, run from `services/inventory`:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe`.
