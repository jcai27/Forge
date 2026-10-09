#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
apps/api/.venv/bin/ruff check apps/api/factory apps/api/tests apps/api/migrations
apps/api/.venv/bin/python -m pytest apps/api/tests -q -c apps/api/pyproject.toml
corepack pnpm --filter @factory/web check
corepack pnpm --filter @factory/web test
corepack pnpm --filter @factory/web test:e2e
