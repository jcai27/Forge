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
The Evaluation Lab also supports replay recordings, expected isolated state, tool
sequences, repeated trials, authored rubrics and independent human review. See
[docs/EVALUATIONS.md](docs/EVALUATIONS.md) for case formats and authorization rules.
Structured requirements and quality policies are visible in Studio. Live architecture
runs in the background worker, and factory role usage contributes to the same cost
ledger as execution. Factory roles retain interrupted-request cost reservations
against build budgets; `/usage` and metrics distinguish them from observed token-cost
estimates. See [docs/FACTORY.md](docs/FACTORY.md) for promotion objectives,
editable thresholds, in-progress build redirection and current limitations.

The builder that improves agents is described in [docs/BUILDER.md](docs/BUILDER.md): a
tool-using optimizer that returns typed patches, screened multi-candidate rounds, examples
and verifiers the runtime executes, optional open-web research (`RESEARCH_ENABLED=true`),
builder-written tools that run only in the sandbox service, connection proposals an
administrator approves, shadow comparison and a release dossier. `BUILDER_MODEL` selects
the model for factory roles. Docker Compose starts the sandbox and sets `SANDBOX_SOCKET`;
`bash scripts/dev.sh` does not, so generated tools fail closed there. Run
`bash scripts/test-sandbox.sh` to prove the sandbox image's isolation. None of the builder
has been run against a real model.

What a build is given (the task, business context documents and example data with correct
answers) is described in [docs/INTAKE.md](docs/INTAKE.md). A build is refused without something
to judge it against. How a build behaves on a real model (what is scored,
retries, parallel scoring, pricing and budgets) is in [docs/RUNNING_BUILDS.md](docs/RUNNING_BUILDS.md).

Credential filtering and retired-ciphertext handling are described in
[docs/SECRET_BOUNDARIES.md](docs/SECRET_BOUNDARIES.md).

## Verification

```sh
bash scripts/test.sh
corepack pnpm --filter @factory/web build
```

The test command runs Ruff, backend pytest, strict TypeScript, Vitest, and Playwright.
Playwright starts isolated API/worker/browser services on 8100/3100 with a fresh database.
A test-only local SDK model prepares the proposal-review fixture through the actual
Test Designer/worker logic before startup. It deliberately proposes one incorrect
expectation for correction in the browser; no evaluation score is seeded. All subsequent
evaluations use the explicitly labeled deterministic fixture runtime, not OpenAI.
This helper only accepts the disposable E2E database and never runs in normal startup.
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

Deployment automation is configured in the Deployments page. Interval schedules and
signed webhooks enqueue durable invocations even when the browser is closed. Each
deployment has per-invocation, lifetime cost and invocation-count limits. Pausing a
deployment blocks queued invocations and pending business approvals. Uncertain external
writes require an administrator to verify and record a provider receipt in Approvals;
the platform never retries an ambiguous side effect automatically.


Workspace membership, invitation acceptance, role changes, removal and workspace switching
are available in Settings. See [ACCESS.md](docs/ACCESS.md) for permission rules and API
contracts. Invitation codes are returned once for private delivery; email is not sent
automatically. Removed or downgraded memberships affect already-issued sessions.


Agent libraries, project/connection selectors, integration and approval lists, candidate
versions, evaluation histories/scenarios and deployment history support bounded Load more
controls. Loaded selections stay available as more records arrive. Collection APIs use
`offset` and `limit` (default 50, maximum 200), including agent suites and deployments.
Secondary audit/trace/trigger lists still need the remaining pagination UX audit.
