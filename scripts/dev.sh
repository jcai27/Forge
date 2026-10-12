#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DATABASE_URL="${DATABASE_URL:-sqlite:///$(pwd)/apps/api/factory.db}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://127.0.0.1:${DEV_API_PORT:-8000}}"
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
# Settings laid over .env for one run, such as the live-model settings of a demo.
if [[ -n "${ENV_OVERLAY:-}" ]]; then
  set -a
  source "$ENV_OVERLAY"
  set +a
fi
uv sync --project apps/api
corepack pnpm install --frozen-lockfile
(cd apps/api && .venv/bin/alembic upgrade head)
apps/api/.venv/bin/uvicorn factory.api:app --app-dir apps/api --host 127.0.0.1 --port "${DEV_API_PORT:-8000}" &
api_pid=$!
apps/api/.venv/bin/python services/worker/main.py &
worker_pid=$!
corepack pnpm --filter @factory/web dev --port "${DEV_WEB_PORT:-3000}" &
web_pid=$!
trap 'kill "$api_pid" "$worker_pid" "$web_pid" 2>/dev/null || true' EXIT INT TERM
wait
