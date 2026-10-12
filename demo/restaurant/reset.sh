#!/usr/bin/env bash
# Put the demo customer back to its starting state. See reset.py. The app may be running or not.
set -euo pipefail
cd "$(dirname "$0")/../.."
export DATABASE_URL="${DATABASE_URL:-sqlite:///$(pwd)/apps/api/factory.db}"
set -a
source .env
source demo/restaurant/live.env
set +a
PYTHONPATH=apps/api exec apps/api/.venv/bin/python demo/restaurant/reset.py "$@"
