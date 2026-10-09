# Agent Factory engineering instructions

The authoritative acceptance criteria are in docs/AGENT_FACTORY_SPEC.md.
Architecture: Next.js frontend (apps/web), FastAPI/SQLAlchemy backend (apps/api),
database-backed resumable worker (services/worker), reusable integrations.
Use Python 3.12+, uv, strict TypeScript, pnpm, Alembic, pytest, Ruff, Playwright.
Commands: bash scripts/dev.sh (local API/worker/web); bash scripts/test.sh
(Ruff, pytest, TypeScript, Vitest, Playwright); corepack pnpm --filter @factory/web build.
Docker: docker compose up --build. Local infrastructure uses isolated project
agent-factory and ports 55432/56379. Tests can use TEST_DATABASE_URL with fresh schemas.
Consult README.md for exact setup and docs/PROGRESS.md for evidence and remaining work.
Worker leases and queued invocations are database-backed. Recovery tests kill real
processes; PostgreSQL-only tests verify concurrent approvals and invocation idempotency.
DEV_API_PORT/DEV_WEB_PORT allow isolated local startup alongside Compose.
Evaluation environments and case formats are documented in docs/EVALUATIONS.md.
Pending human/rubric reviews halt promotion; reviews preserve deterministic failures.
Replay must never instantiate a live adapter. Imported mappings require explicit
administrator/model-visibility authorization and select only declared fields.
Builder policies/accounting are documented in docs/FACTORY.md. Live architecture runs
in the worker; model candidates cannot change user quality policies or expand resource
ceilings. Role usage records use job_id and a nullable run_id; runtime/grading records
use run_id. Read PLANS.md's current priorities rather than older progress snapshots.
Generated test proposals are not evidence: keep them outside evaluation_cases until
administrator correction/acceptance. No proposed plan can grant live/imported access.

Invariants: tenant ownership is checked server-side on every resource access;
immutable versions; evaluations use isolated state; production writes require
explicit authorization; secrets never enter model context or browser responses;
no arbitrary generated code; promotion requires measured regression-safe evidence.
Demo mode is explicitly labeled and never represented as live model execution.
Tests must exercise behavior and security boundaries, not invented score overrides.

Continue from PLANS.md and docs/PROGRESS.md. Update both after verified milestones.
Do not declare phases complete without executing their checks. Document unavailable
external credentials and independently continue local functionality.
