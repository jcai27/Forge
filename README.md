# Agent Factory

A full-stack workspace for constructing, evaluating and improving versioned business
agents. The authoritative product specification is [docs/AGENT_FACTORY_SPEC.md](docs/AGENT_FACTORY_SPEC.md).
Implementation and verification status is tracked in [docs/PROGRESS.md](docs/PROGRESS.md).

## Local startup

Prerequisites: Python 3.12+, uv, Node 24+, Corepack. From the repository root:

```sh
corepack pnpm install
uv sync --project apps/api
bash scripts/dev.sh
```

Open http://localhost:3000 and select **Open local demo workspace**. This explicitly
local development login creates a fictional organization, project and ERP connection.
The login endpoint is disabled outside development. Register/sign-in also work.
SQLite persists local history at `apps/api/factory.db`; a separate worker continues
builds when the browser closes. Startup runs migrations and terminates all three
processes when interrupted.

Optional configuration: copy `.env.example` to `.env` and edit it. Never commit secrets.
If setting `DATABASE_URL`, use an absolute SQLite path to keep worker/API state aligned.

For PostgreSQL and Redis with the complete application:

```sh
docker compose up --build
```

Compose uses the isolated project name `agent-factory`. PostgreSQL is published locally
on 55432 and Redis on 56379 to avoid collisions. API and browser are on 8000/3000.
Run database services alone with `docker compose up -d postgres redis`, then set:

```sh
export DATABASE_URL=postgresql+psycopg://factory:local-factory-password@127.0.0.1:55432/factory
export REDIS_URL=redis://127.0.0.1:56379/0
bash scripts/dev.sh
```

## First workflow

Create a project in **Create agent**, choose an orders/quotes/hiring starter or describe
your own workflow, and attach the Fictional Business ERP. Start a build and inspect its
recorded events, failed cases, hypotheses, new versions, comparisons and held-out tests.
The order starter deliberately begins without alias/typo matching so independent tests
reveal deficiencies and the loop has real measurable improvements to make.

Inspect **Evaluations** and **Versions**, approve the best candidate in **Deployments**,
then deploy and invoke it. `Harbor Bistro: 2 kg red toms` exercises customer aliases and
pricing. Writes remain pending until an administrator reviews the exact action in
**Approvals**. Trace history persists after reload. Hiring focuses on administrative
coordination, with communication approval and no automated screening.

## Live model mode

Set `EXECUTION_MODE=live`, `OPENAI_API_KEY` and `OPENAI_MODEL` server-side, then restart.
The installed OpenAI Agents SDK drives generation, optimization and execution. Demo
mode uses an explicit deterministic Model adapter with the real SDK Runner and actual
registered tool dispatch; it does not call or impersonate a live language model.

No live API key is configured in the current development environment, so live provider
execution remains unverified. General custom workflows require live mode and authored
evaluation cases; the deterministic adapter supports the three provided business templates.
Costs are estimates from recorded tokens and `ESTIMATED_TOKEN_COST`; set this conservative
per-token estimate for your chosen model. Scores are provisional fixture pass rates,
with finite-sample intervals, rather than claims of real-world accuracy.

## Verification

```sh
bash scripts/test.sh
corepack pnpm --filter @factory/web build
```

The test command runs Ruff, backend pytest, strict TypeScript, Vitest, and Playwright.
Playwright starts isolated API/worker/browser services on 8100/3100 with a fresh database.
Install its browser once with `corepack pnpm --filter @factory/web exec playwright install chromium`.
To run backend acceptance tests on local PostgreSQL using isolated per-test schemas:

```sh
TEST_DATABASE_URL=postgresql+psycopg://factory:local-factory-password@127.0.0.1:55432/factory \
  apps/api/.venv/bin/python -m pytest apps/api/tests -q -c apps/api/pyproject.toml
```

## API and integration setup

Interactive OpenAPI: http://127.0.0.1:8000/docs. Exported contract:
`packages/contracts/openapi.json`; shared frontend types: `packages/contracts/src/index.ts`.
Every application resource requires a bearer token and organization membership.
Collection endpoints use `offset`/`limit` with a total count.

Example invocation after authorized deployment:

```sh
curl http://127.0.0.1:8000/deployments/DEPLOYMENT_ID/invoke \
  -H "Authorization: Bearer YOUR_TOKEN" -H 'Content-Type: application/json' \
  -d '{"input":{"text":"Harbor Bistro: 2 kg Tomatoes"},"idempotency_key":"order-001"}'
```

See [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Production needs a strong `JWT_SECRET`, a Fernet `ENCRYPTION_KEY`, PostgreSQL and Redis.
Generate a Fernet key using `.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
from apps/api. Set `ENVIRONMENT=production` to enforce these settings and disable demo login.
Keep secrets in your deployment secret manager. Real business writes require separate
explicit authorization; no development or evaluation command performs them.
