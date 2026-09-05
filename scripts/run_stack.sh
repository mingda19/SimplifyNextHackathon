#!/usr/bin/env bash
# Start the local backend stack: inventory (8000), feedback (8002), forecaster (8003).
# Native Postgres, not Docker — this machine has no Docker runtime.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv/bin"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://simplifynext:simplifynext@localhost:5432/simplifynext}"
export AWS_CONFIG_FILE="$ROOT/aws/config" AWS_PROFILE="${AWS_PROFILE:-hackathon}"
export OMP_NUM_THREADS=1

start () { # name dir module port
  local name=$1 dir=$2 mod=$3 port=$4
  if curl -sf -m 1 "http://localhost:$port/health" >/dev/null 2>&1; then
    echo "  $name already up on :$port"; return
  fi
  ( cd "$ROOT/$dir" && PYTHONPATH=. nohup "$VENV/uvicorn" "$mod" --port "$port" \
      > "/tmp/${name}.log" 2>&1 & )
  for _ in $(seq 1 40); do
    curl -sf -m 1 "http://localhost:$port/health" >/dev/null 2>&1 && { echo "  $name up on :$port"; return; }
    /usr/bin/python3 -c "import time;time.sleep(0.5)"
  done
  echo "  $name FAILED to start — see /tmp/${name}.log"
}

start inventory  services/inventory       app.main:app 8000
start feedback   services/feedback        app.main:app 8002
start forecaster services/price_forecaster app:app     8003
