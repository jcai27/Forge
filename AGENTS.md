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
use run_id. Factory model calls commit pending UsageRecords/reserved_cost before dispatch;
observed responses settle them, unresolved calls retain uncertain reservations in the
build budget. Do not count reserved_cost as observed token usage or billing. Preserve
pause/cancel and lease ownership when committing results after provider I/O.
Read-only rubric calls also commit pending run/job UsageRecords before dispatch, retain
unknown reservations, disable hidden HTTP retries and settle observed usage independently
of grade validity. build_accounted_cost prevents charging observed run costs twice.
Manual grading rechecks the pending result after I/O; competing calls retain both charges
but publish one grade. Include reservations in budget ceilings, never in observed cost
or tokens; unknown charges cannot prove a cost improvement. Do not reuse grading hooks
for production tool transactions: deployment/production durable accounting still needs
its own transaction design. Live evaluated-agent calls now use evaluation_agent ledgers
and control checks at model/tool boundaries. Recover abandoned calls as uncertain and
mark their orphaned execution failed; rerun only within the remaining build budget.
Read PLANS.md's current priorities rather than older progress snapshots.
Build redirection requires a fresh immutable version/evaluation and retains global
time/cost/iteration limits. Never reuse previous scorecards for a revised objective or
allow a stale returning worker to overwrite the redirected checkpoint.
Generated test proposals are not evidence: keep them outside evaluation_cases until
administrator correction/acceptance. No proposed plan can grant live/imported access.

Credential filtering is documented in docs/SECRET_BOUNDARIES.md. Apply tenant-scoped
known-value filtering at model/tool/output/browser boundaries. Retired ciphertext is
redaction-only and must never be used for connector authentication or exposed by APIs.
Preserve historical filtering when removing or rotating active credentials.

REST response handling must bound wire and decoded bytes during streaming, including
compressed bodies. Keep total HTTP deadlines and close discarded streams. Never retry
HTTP write methods automatically; uncertain results go through reconciliation.
REST/MCP egress uses origin-scoped pinned transports: validate every DNS result, connect
to numeric public IPs and preserve original HTTP/TLS identity. Do not replace this with
preflight DNS followed by an ordinary client connection, enable environment proxies or
redirects, or permit private/transition destinations. MCP 2 requires native httpx2
transport/stream types and snake_case SDK attributes. Loopback remapping and custom
test certificates are owned-test-fixture dependencies, never user configuration.
MCP responses share wire/decoded limits across a client session, before JSON/SSE parsing.
Keep bounded decompression, pagination limits and whole-operation deadlines. An exhausted
decoded budget must never reach zlib with max_length=0 (which means unlimited output).
Do not enable automatic tool-call retries or expose resource ceilings as server overrides.

Invariants: tenant ownership is checked server-side on every resource access;
immutable versions; evaluations use isolated state; production writes require
explicit authorization; secrets never enter model context or browser responses;
no arbitrary generated code; promotion requires measured regression-safe evidence.
Demo mode is explicitly labeled and never represented as live model execution.
Tests must exercise behavior and security boundaries, not invented score overrides.

Continue from PLANS.md and docs/PROGRESS.md. Update both after verified milestones.
Do not declare phases complete without executing their checks. Document unavailable
external credentials and independently continue local functionality.
