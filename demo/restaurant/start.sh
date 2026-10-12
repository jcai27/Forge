#!/usr/bin/env bash
# Start the app for the restaurant demo: the ordinary dev script, with agents and page reading on the live model.
# Stop it with Ctrl-C. The customer platform is at http://localhost:3000/portal.
set -euo pipefail
cd "$(dirname "$0")/../.."
ENV_OVERLAY="$(pwd)/demo/restaurant/live.env" exec bash scripts/dev.sh
