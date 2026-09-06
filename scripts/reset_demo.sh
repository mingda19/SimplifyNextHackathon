#!/usr/bin/env bash
# Restore the database to a known pre-demo state.
#
# WHY THIS EXISTS
# The agent is good at its job: one approved run places orders, resolves the
# feedback those orders address, and the deficits it was demonstrating are gone.
# Re-running the demo then shows an agent with nothing to do. This puts the
# world back so the demo is repeatable.
#
#   ./scripts/reset_demo.sh            # reset to the seeded demo state
#   ./scripts/reset_demo.sh --snapshot # capture the CURRENT state as the baseline
#
# Docker is not used here — this machine runs Postgres natively. compose.yaml
# only covers postgres + inventory and does not seed feedback, auth or agent
# state, so it cannot serve as the reset path.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv/bin"
DB=simplifynext
U=simplifynext
SNAP="$ROOT/data/demo_baseline.sql"

if [ "${1:-}" = "--snapshot" ]; then
  mkdir -p "$(dirname "$SNAP")"
  pg_dump -U "$U" -d "$DB" --data-only \
    --table='public.items' --table='public.lots' --table='public.vendors' \
    --table='public.vendor_offers' \
    > "$SNAP"
  echo "  snapshot written: $SNAP ($(wc -l < "$SNAP") lines)"
  exit 0
fi

echo "  resetting demo state..."

# 1. clear everything the agent produces
psql -U "$U" -d "$DB" -q <<'SQL'
TRUNCATE public.orders;
DELETE FROM agent.runs;
UPDATE feedback.feedback_entries
   SET resolved_at = NULL, resolved_by_run = NULL, resolution_note = NULL;
SQL
echo "    cleared orders, agent runs, feedback resolutions"

# 2. restore stock levels and lots
if [ -f "$SNAP" ]; then
  psql -U "$U" -d "$DB" -q -c "TRUNCATE public.lots, public.vendor_offers, public.orders CASCADE;" \
                            -c "DELETE FROM public.items;" \
                            -c "DELETE FROM public.vendors;"
  psql -U "$U" -d "$DB" -q -f "$SNAP"
  echo "    restored items/lots/vendors from snapshot"
else
  ( cd "$ROOT/services/inventory" && \
    DATABASE_URL="postgresql+psycopg://$U:$U@localhost:5432/$DB" \
    PYTHONPATH=. "$VENV/python" -m app.seed --reset >/dev/null 2>&1 ) \
    || ( cd "$ROOT/services/inventory" && \
         DATABASE_URL="postgresql+psycopg://$U:$U@localhost:5432/$DB" \
         PYTHONPATH=. "$VENV/python" -m app.seed >/dev/null )
  echo "    re-seeded inventory from app.seed"
fi

# 3. LangGraph checkpoints — a stale thread would resume a dead plan
rm -f "$ROOT/services/orchestrator/checkpoints.db" \
      "$ROOT/services/orchestrator/checkpoints.db-wal" \
      "$ROOT/services/orchestrator/checkpoints.db-shm"
echo "    cleared agent checkpoints"

# 4. report the state the demo will start from
"$VENV/python" - <<'PY'
import os, re, psycopg2, psycopg2.extras
dsn = "postgresql://simplifynext:simplifynext@localhost:5432/simplifynext"
c = psycopg2.connect(dsn); cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT count(*) n FROM items"); items = cur.fetchone()["n"]
cur.execute("SELECT count(*) n FROM items WHERE on_hand < reorder_point"); low = cur.fetchone()["n"]
cur.execute("SELECT count(*) n FROM orders"); orders = cur.fetchone()["n"]
cur.execute("SELECT count(*) n FROM feedback.feedback_entries WHERE resolved_at IS NULL AND extraction_status='done'")
open_fb = cur.fetchone()["n"]
cur.execute("SELECT count(*) n FROM agent.runs"); runs = cur.fetchone()["n"]
print(f"\n  demo starts from:")
print(f"    {items} items, {low} below reorder point")
print(f"    {orders} open orders (should be 0)")
print(f"    {open_fb} unresolved feedback entries")
print(f"    {runs} agent runs (should be 0)")
print("\n  restart the orchestrator so it picks up a fresh checkpoint file:")
print("    pkill -f 'orchestrator.api:app' && ./scripts/run_stack.sh\n")
PY
