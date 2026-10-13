#!/usr/bin/env bash
# Open and fill the sample operations workspace. See seed.py. The app may be running or not.
set -euo pipefail
cd "$(dirname "$0")/../.."
export DATABASE_URL="${DATABASE_URL:-sqlite:///$(pwd)/apps/api/factory.db}"
set -a
source .env
set +a
(cd apps/api && .venv/bin/alembic upgrade head)
cd apps/api
PYTHONPATH=. exec uv run -q --with reportlab python ../../demo/operations/seed.py "$@"
