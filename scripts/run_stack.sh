#!/usr/bin/env bash
# Start the whole local stack.
#   auth 8001 · inventory 8000 · feedback 8002 · forecaster 8004 · orchestrator 8003
#   frontend (Vite) 5173
# Native Postgres, not Docker — this machine has no Docker runtime.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv/bin"
# Parse .env as data and export it before the shell supplies any defaults.
if [ "${PANTRY_ENV_LOADED:-0}" != "1" ]; then
  exec "$VENV/python" - "$ROOT" "$@" <<'PY'
import os
import sys
from pathlib import Path
from dotenv import dotenv_values
root = Path(sys.argv[1])
env = {k: v for k, v in dotenv_values(root / '.env').items() if v is not None}
env.update(os.environ)
env['PANTRY_ENV_LOADED'] = '1'
os.execvpe('bash', ['bash', str(root / 'scripts/run_stack.sh'), *sys.argv[2:]], env)
PY
fi
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://simplifynext:simplifynext@localhost:5432/simplifynext}"
export AWS_CONFIG_FILE="$ROOT/aws/config" AWS_PROFILE="${AWS_PROFILE:-hackathon}"
export OMP_NUM_THREADS=1

api () { # name dir module port
  local name=$1 dir=$2 mod=$3 port=$4
  if curl -sf -m 1 "http://localhost:$port/health" >/dev/null 2>&1; then
    echo "  $name        already up on :$port"; return
  fi
  ( cd "$ROOT/$dir" && PYTHONPATH="$ROOT/services:." nohup "$VENV/uvicorn" "$mod" --port "$port" \
      > "/tmp/${name}.log" 2>&1 & )
  for _ in $(seq 1 40); do
    curl -sf -m 1 "http://localhost:$port/health" >/dev/null 2>&1 && { printf "  %-12s up on :%s\n" "$name" "$port"; return; }
    /usr/bin/python3 -c "import time;time.sleep(0.5)"
  done
  printf "  %-12s FAILED — see /tmp/%s.log\n" "$name" "$name"
}

api auth         services/auth             app.main:app        8001
api inventory    services/inventory        app.main:app        8000
api feedback     services/feedback         app.main:app        8002
api forecaster   services/price_forecaster app:app             8004
api orchestrator services                  orchestrator.api:app 8003

if [ "${1:-}" = "--with-frontend" ]; then
  if lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  frontend     already up on :5173"
  else
    ( cd "$ROOT/frontend/app" && nohup npm run dev > /tmp/frontend.log 2>&1 & )
    for _ in $(seq 1 60); do
      curl -sf -m 1 "http://localhost:5173" >/dev/null 2>&1 && break
      /usr/bin/python3 -c "import time;time.sleep(0.5)"
    done
    echo "  frontend     up on :5173"
  fi
  echo
  echo "  Open http://localhost:5173"
fi
