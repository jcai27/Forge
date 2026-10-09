#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
task_db=$(mktemp /tmp/factory-e2e-XXXXXX)
export DATABASE_URL="sqlite:///$task_db"
export EXECUTION_MODE=demo
export ENVIRONMENT=development
export CORS_ORIGINS='["http://127.0.0.1:3100"]'
apps/api/.venv/bin/uvicorn factory.api:app --app-dir apps/api --host 127.0.0.1 --port 8100 &
api_pid=$!
apps/api/.venv/bin/python services/worker/main.py &
worker_pid=$!
trap 'kill "$api_pid" "$worker_pid" 2>/dev/null || true; rm -f "$task_db"' EXIT INT TERM
wait
