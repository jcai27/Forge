#!/usr/bin/env bash
# Build the operations demo: documents, agents, workspace. See build.py. The app must be running.
set -euo pipefail
cd "$(dirname "$0")/../.."
bash demo/operations/seed.sh >/dev/null
cd apps/api
PYTHONPATH=. exec uv run -q --with reportlab python ../../demo/operations/build.py "$@"
