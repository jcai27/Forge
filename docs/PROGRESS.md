# Progress

2026-10-08: inspected empty repository and authoritative specification. Copied the
specification to the requested docs path. Created engineering conventions and roadmap.
Read official Agents SDK quickstart; will verify installed APIs before runtime work.
No acceptance test has passed yet. Next: dependency setup, schema and service foundation.

Backend vertical slice (verified): SQLAlchemy schema with 25 tables; installed
openai-agents 0.23.1 and inspected Agent/Runner/FunctionTool/Model signatures.
Real SDK Runner executes registered tools via an explicitly deterministic no-LLM
model adapter in demo mode. Fictional ERP includes 100 products and 36 independent
order cases, plus quote/hiring fixtures. Persistent stage/case checkpoints survive
fresh worker sessions. Two evidence-derived candidate changes repair alias and typo
failures; critical regression protection and final held-out validation are tested.

Verification: 10 pytest tests passed (runtime, improvement, regression, recovery,
API creation/editing, tenant/RBAC boundaries, encrypted secrets, imported data model
visibility, approval/deployment/invocation/rollback). API supports persisted progress,
OpenAPI, integration management, evaluations, version review, deployments and logs.
No live model execution verified yet. No browser test yet. Docker client exists but
daemon is not running. Next: frontend, service startup, connector tests and hardening.

Full browser vertical slice verified: all required UI routes are implemented with
TanStack Query, React Flow, Recharts, forms and actual API controls. Strict TypeScript
and optimized Next.js build pass. Playwright creates a project, builds an order agent,
observes three iterations and real failures, inspects cases/version differences,
approves/deploys/invokes, approves a fixture ERP write, and reopens persistent history.
Rendered dashboard inspected. Vitest: 2 tests pass. Backend: 20 tests pass on SQLite;
18 tests (before the two additional template checks) passed on PostgreSQL using fresh
per-test schemas. Quote and hiring templates also pass their independent suites and
approval-gated writes through the shared factory/runtime.

Hardening so far: pinned connector contract snapshots/fingerprints; revocation checked
again at approval; pre-call conservative token cost reservation; signed/deduplicated
private webhook imports; isolated worker sessions; external dispatch intent persisted
before I/O with no blind retries. README, .env.example, Compose and integration setup
documentation are present. Frozen Alembic migration applies cleanly to SQLite and
PostgreSQL, with no schema drift. Both Docker app images built successfully.
Docker infrastructure runs under isolated project agent-factory (DB port 55432).

Outstanding scope (goal remains active): deployment schedules and invocation webhooks;
replay integration environments/authorized live read-only evaluation; qualitative
rubric grading and explicit variability; true worker process kill/recovery and concurrent
approval tests; general live workflow/role integration and model-call cost accounting
across builder roles; production data minimization and additional input/budget checks;
frontend pagination/redirect editing and expanded usability checks; full Compose startup
and requirements-by-requirements acceptance audit. OPENAI_API_KEY is absent, so actual
provider calls are unverified; no external credentials or production writes were used.

Compose startup verified: PostgreSQL, Redis, API, worker and built Next.js frontend
are running; API health returns demo mode and /dashboard returns HTTP 200. Startup
migration completed. API/frontend images build with frozen dependency locks. Final
local verification after tenant-write locking: 20 backend tests pass, Ruff clean,
TypeScript clean. See docs/ACCEPTANCE.md for requirement-level evidence and gaps.
