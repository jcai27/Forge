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

2026-10-09 deployment/recovery milestone verified: manual, scheduled and HMAC-signed
webhook invocations share a durable database queue. A worker rechecks authorization,
deployment state and pinned versions before execution. Cost reservations/lifetime and
invocation limits are enforced. Administrators can record independently verified
receipts to reconcile uncertain external dispatch without sending again. The frontend
provides scheduling/webhook controls, invocation history, limits and reconciliation.

Two tests kill real worker processes during an uncommitted build trial and invocation,
then restart after lease expiry: checkpoints survive, cases/approvals are not duplicated,
and business writes remain pending. PostgreSQL concurrency tests prove that competing
stock approvals and duplicate incoming requests apply once; concurrent idempotent
enqueue creates one invocation. Tenant locking protects newly inserted order records.
Real PostgreSQL connector discovery/read succeeds; unapproved tables and writes fail.
The fictional catalog now contains 100 named products, and fractional prices round to
cents using an explicit policy verified against independently authored expectations.

Executed checks: Ruff clean; 29 SQLite tests passed, 4 PG-only skipped; 33 PostgreSQL
tests passed; strict TypeScript; 2 Vitest tests; complete Playwright path including
schedule creation/disabling; optimized Next image build; updated API/worker/web Compose
startup; API health and dashboard HTTP 200. Local startup was separately verified on
8200/3200 with the documented script. Schema migration 0002 is applied to local PG.

Remaining scope supersedes the older outstanding list: replay and authorized read-only
evaluation, expected test-state/tool-sequence assertions, qualitative/human grading,
explicit repeated-trial variability, structured general builder roles and full model
budget accounting, imported-data minimization/mapping, membership management,
configurable quality policies, frontend pagination/mobile/accessibility and security
transport/deployment hardening. OPENAI_API_KEY/external credentials remain absent;
actual live provider calls are unverified. No unauthorized production writes occurred.

2026-10-09 evaluation milestone verified: ReplayConnector consumes exact ordered
tool/argument/response recordings and never constructs live adapters. External writes
can be simulated in replay; authorized live checks reject them. Administrator grants,
tool/version scopes, connection revocation and imported-resource visibility are checked
server-side. Field mappings copy only selected columns into fresh test forks; imported
private columns and full state snapshots stay outside recorded grading evidence.

Assertions now cover expected test records, JSON schemas and actual tool sequences,
alongside independent arithmetic, completion, approval and safety checks. Permission
violations fail safety even when no mutation occurred. Scorecards expose per-case
repeated-trial variability and pending reviews. Optional SDK rubric grading records
criterion evidence and observed usage under case/build/time budgets. Unavailable live
grading is explicitly pending. Human reviewers resolve only human checks, retain every
deterministic failure and leave audit evidence; builds pause and resume the same trials.
The lab exposes these metrics and review/retry controls. An explicit higher-score
candidate that fixes development cases but breaks critical stock regression is rejected.

Executed final checks: bash scripts/test.sh passes (Ruff, 39 backend tests with 4 PG-only
skips, strict TypeScript, 2 Vitest tests, complete browser flow including authored human
case/retest/review). The PostgreSQL suite passes all 43 tests. Alembic 0003 applies
without drift on both databases. A populated SQLite evaluation history survives upgrade,
downgrade and re-upgrade with foreign keys enabled. Docker images build; rebuilt
Compose API/worker/web/PG/Redis run; health, dashboard and new review routes are verified.

Remaining next: persistent structured requirements and genuine background builder/test
design roles; complete builder/optimizer usage accounting and budgets; configurable
quality policies/objectives; broader live template/custom role contracts; membership
management; pagination, mobile/accessibility and redirect UX; SSRF/DNS/streaming bounds,
non-root deployment and full tenant/schema/security audit. Actual OpenAI/provider
execution, real email/OAuth/MCP credentials remain unavailable. The goal stays active;
passing local fixtures and transport contracts do not establish live model correctness.

2026-10-09 builder accounting/quality milestone verified: baseline versions persist
structured requirements (objective, inputs/outputs, systems, steps, rules, exceptions,
success metrics, permissions and assumptions). Live architecture runs in DESIGNING
through the actual SDK and creates an immutable version. SDK design/optimization use
bounded output, schema-aware pre-call reservations, remaining build cost/time and a
shared usage ledger. Measured role usage persists on handled scope/output failure.
Zero budget prevents model dispatch. The studio displays requirements and user policy.

Quality policies now configure score/evidence counts, latency/cost limits, promotion
objective and minimum improvement. Administrator edits create new versions. Models
cannot change policy or increase resource ceilings. Readiness and deployment review
apply the configured gates; critical/safety/split/review gates remain mandatory.
Every previously passing regression trial must remain passing, so equal aggregate
regression scores cannot hide a newly broken scenario. Cost/latency objectives retain
measured task quality. An unchanged model candidate is explicitly identified as such.

Final executed checks: bash scripts/test.sh passes (Ruff, 45 SQLite tests and 4 PG-only
skips, TypeScript, 2 Vitest tests, complete browser flow); all 49 PG tests pass. SDK
provider contracts cover background design success/failure, optimizer usage/development
input scope, pre-dispatch zero-budget rejection, quality counts/latency and admin edits.
Migration 0004 applies without drift on SQLite/PG; populated upgrade/downgrade retains
evaluation history and existing runtime usage. API/web images build, rebuilt Compose
runs and health/dashboard/schema checks pass. No actual provider credentials were used.

Remaining highest priorities: general background Test Designer and reviewed proposed
cases/custom workflow builds; durable accounting when a process dies during an unresolved
provider request; build redirection; known-secret-value/private-output minimization;
streaming/DNS transport hardening and non-root deployment; memberships, pagination,
mobile/accessibility and full acceptance audit. Actual provider/grade correctness remains
unverified without credentials. The full goal remains active; this is a verified milestone.
