#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
task_db=$(mktemp /tmp/factory-e2e-XXXXXX)
api_pid=''
worker_pid=''
cleanup() {
  if [[ -n "$api_pid" ]]; then kill "$api_pid" 2>/dev/null || true; fi
  if [[ -n "$worker_pid" ]]; then kill "$worker_pid" 2>/dev/null || true; fi
  rm -f "$task_db"
}
trap cleanup EXIT INT TERM
export DATABASE_URL="sqlite:///$task_db"
export EXECUTION_MODE=demo
export ENVIRONMENT=development
export CORS_ORIGINS='["http://127.0.0.1:3100"]'
(
  cd apps/api
  .venv/bin/alembic upgrade head
)
PYTHONPATH=apps/api apps/api/.venv/bin/python apps/api/tests/helpers/seed_browser_proposals.py
apps/api/.venv/bin/uvicorn factory.api:app --app-dir apps/api --host 127.0.0.1 --port 8100 &
api_pid=$!
apps/api/.venv/bin/python services/worker/main.py &
worker_pid=$!
wait
