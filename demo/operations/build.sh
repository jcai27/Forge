#!/usr/bin/env bash
# Build the operations demo: documents, agents, workspace. See build.py. The app must be running.
set -euo pipefail
cd "$(dirname "$0")/../.."
# The workspace hangs off the local demo builder, which exists once someone has signed in to it.
[[ "${1:-}" == "--documents-only" ]] || curl -sf -X POST "${FACTORY_API:-http://127.0.0.1:8000}/auth/demo" >/dev/null \
  || { echo "The app is not answering. Start it first: bash demo/restaurant/start.sh" >&2; exit 1; }
[[ "${1:-}" == "--documents-only" ]] || bash demo/operations/seed.sh >/dev/null
cd apps/api
PYTHONPATH=. exec uv run -q --with reportlab python ../../demo/operations/build.py "$@"
