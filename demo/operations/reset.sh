#!/usr/bin/env bash
# Put the operations demo back to its starting state. See reset.py. The app may be running or not.
set -euo pipefail
cd "$(dirname "$0")/../.."
export DATABASE_URL="${DATABASE_URL:-sqlite:///$(pwd)/apps/api/factory.db}"
set -a
source .env
set +a
cd apps/api
PYTHONPATH=. exec uv run -q --with reportlab python ../../demo/operations/reset.py "$@"
