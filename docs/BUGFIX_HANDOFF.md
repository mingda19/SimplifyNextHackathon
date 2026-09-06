# Workstream 4 bug-fix handoff

This branch repairs the blockers recorded in [READINESS_AUDIT.md](READINESS_AUDIT.md). The audit remains the historical baseline, not a claim that its original 31 failures still describe this branch.

## Changes

- **Approval boundary:** `act` calls `/quote` or `/allocate/validate`. Only an approved Type B `commit` calls `/order` or `/allocate`. Quote-only steps never buy. Type A emits a checklist ranked by unmet-need urgency × days-cover shortfall, with review flags separate.
- **Replay and concurrency:** inventory persists each idempotency key, request fingerprint and response in the same transaction as the mutation. Order, receipt and allocation retries return the original result. Conflicting reuse returns 409. PostgreSQL locks serialize competing decisions and purchases. Interrupted commits can be retried by the same approver, with the same keys.
- **Permissions:** inventory, feedback reads/metrics and agent endpoints require authentication. Recipient accounts can submit feedback but cannot operate inventory or approve runs. The approver comes from signed identity, never `decided_by` in JSON. Internal requests use a separate service credential that cannot authorize a human approval. Public feedback requires an active request link; recipient identity is assigned from the account or a pseudonymous participant identifier. This is one shared charity workspace, not a multi-tenant isolation model.
- **Money:** one adapter normalizes `total_price_sgd`, `total_sgd`, and quantity × unit price. The single-order warning checks each order. PostgreSQL enforces the S$5,000 monthly purchasing ceiling across concurrent requests. Commit rejects a changed quoted price. A failed multi-step commit exposes any completed orders and its failure instead of reporting success.
- **Stock:** `POST /inventory/{sku}/receive` atomically creates a lot and increases stock. Source and expiry are required. Direct `on_hand` patches that change quantity are rejected. Opening stock requires lot metadata; the UI creates an empty item and records opening lots through Incoming. Expired receipts, booleans, fractional counts and values above PostgreSQL INTEGER capacity are rejected.
- **Integration:** pricing uses port 8004; the agent uses 8003. Compose includes the real forecaster, service DNS addresses, schema bootstrap for existing volumes, and an orchestrator volume at `/data`. `FAKE_SERVICES=0` connects live services; `FAKE_LLM=1` remains the default to avoid paid model calls. The Bedrock dependency extra is declared.
- **Other fixes:** reserved SKU validation, blank feedback, bounded run-list limits, `Retry-After` backoff, real lot validation/adaptation, JSON dashboard summaries, failed-predict status, revoked-link checks, live catalogue refresh/degradation, consistent login names, Type A selection and collapsible node traces. Checkpoint sidecars are removed from source and excluded from images.
- **Calibration:** the API reports `*_at_gate` statistics only when the artifact's measured threshold matches the active gate. Otherwise they are `null`, with threshold provenance. Regenerating calibration now stores measurements for every supported gate; existing measurements are not relabelled or invented.

## Start or upgrade

Install Docker and Node.js. From the repository root:

1. Copy `.env.example` to `.env`. Set `AUTH_JWT_SECRET` and `SERVICE_AUTH_TOKEN` to **different** random values, each at least 32 characters. Generate each with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. Run `docker compose up --build -d`. The bootstrap service upgrades the auth/feedback/agent schemas, and inventory runs Alembic including `0002_operation_replay`. Do not delete named volumes when rebuilding.
3. In `frontend/app`, run `npm ci` and `npm run dev`. Sign in before accessing stock, feedback or agent actions.

| Service | Local port |
|---|---|
| Inventory | 8000 |
| Auth | 8001 |
| Feedback | 8002 |
| Agent | 8003 |
| Pricing | 8004 |
| Frontend | 5173 |

For native Python processes, install `pip install -e . -r tests/readiness/requirements.txt` from the repository root. Run the schemas and `alembic upgrade head` against the configured PostgreSQL database before `scripts/run_stack.sh`. Individual service tests run in separate Python processes because inventory, auth and feedback each use a package named `app`.

```bash
PYTHONPATH=services/inventory:services .venv/bin/python -m pytest services/inventory/tests -q
PYTHONPATH=services .venv/bin/python -m pytest services/orchestrator/tests -q
PYTHONPATH=services/feedback:services .venv/bin/python -m pytest services/feedback/tests -q
.venv/bin/python scripts/test_readiness.py
```

The readiness runner uses its own disposable PostgreSQL container, synthetic credentials and fake model inference. Its checks cover real HTTP/SQL boundaries, concurrent orders/approvals, replay, role restrictions, receipts and the five adaptation errors. For a checkpoint-volume check, start a pending run, replace only the orchestrator with `docker compose up -d --force-recreate orchestrator`, then approve that same run. There must be no order before approval and exactly one afterwards.

## Verification in this editing session

- **41 contract tests passed** with the available Anaconda Python/Pydantic environment.
- SQLAlchemy created the SQLite schema; order and lot response serialization passed.
- All Python files parsed; all 13 frontend JS/JSX files passed TypeScript syntax transpilation; Compose YAML parsed; `git diff --check` passed.
- **Full service, graph and PostgreSQL readiness tests remain unverified here.** This machine has no Docker/PostgreSQL or standalone Node/npm. Python dependency downloads failed DNS resolution both inside the sandbox and after approval. The full frontend production build and live Bedrock calls were not run.

## Before the demo

Run the full checks above on a machine with dependencies and Docker. Review any **pre-fix** orders: the old code may already have purchased them, and rejection cannot reverse a vendor purchase. Old approval checkpoints are explicitly blocked from committing again. Legacy stock with missing lots needs real source/expiry information before reconciliation; this change does not invent that information.

The next Workstream 4 work is live-Claude validation, richer plan revision/Modify controls, and the rehearsed demo. Halted plans must currently be rejected and replanned in a new run. Existing calibration statistics at a different gate remain unavailable at the active gate until recalibration is run.
