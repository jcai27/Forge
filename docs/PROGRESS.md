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

2026-10-09 reviewed Test Designer milestone verified: a live build with no cases invokes
a general SDK role using structured requirements, rules and approved tool schemas.
Typed proposals require six distinct scenarios, all three splits, assertions and a
critical regression case. Tool recordings are checked against actual authorized schemas;
live/imported access grants are rejected. Role token/cost usage is recorded.

Proposals remain in the build checkpoint, outside the evaluation library. The build
page provides a correction/review form. An administrator accepts a corrected plan,
atomically imports cases, records review/audit evidence and resumes the same build.
Repeated acceptance cannot duplicate cases. Existing authored suites bypass proposal
generation. The optimizer still receives only development failures, not held-out answers.
Deterministic custom mode continues to require authored cases rather than claiming a
model-generated plan. Actual general-provider plan quality remains unverified.

SDK contract tests prove the proposal/review boundary, editor rejection, correction of
an incorrect price expectation, rejected live-access proposal and recorded usage. The
accepted authored expectations are then exercised through the actual SDK fixture tool,
independent grading, development/regression comparison and held-out readiness. No score
overrides are used. Final checks: Ruff; 47 SQLite tests passed (4 PG-only skips); all
51 PostgreSQL tests passed; TypeScript; 2 Vitest tests; existing full browser journey;
optimized Docker images; rebuilt Compose health/dashboard/proposal-route checks.
The proposal form is type/build checked; its own browser interaction still needs an
expanded scenario. No real provider credentials or production writes were used.

Next: durable provider-call reservation/recovery, build redirection and broader custom
connector workflows; known-secret/private-data and transport hardening; memberships,
pagination/mobile/accessibility; complete acceptance audit. Goal remains active.


2026-10-09 durable factory provider accounting milestone verified: architecture,
test design and optimization persist a pending usage reservation before SDK dispatch.
Observed responses replace it with recorded tokens and the configured cost estimate.
Interrupted/failed requests retain uncertain reservations against the build budget;
no unknown tokens or provider invoice amounts are invented. Lease recovery marks
abandoned pending requests uncertain and permits retries only within remaining budget.
Factory HTTP automatic retries are disabled. Roles have bounded stage timeouts and
leases covering the request. Returning workers preserve user pause/cancel decisions
and cannot persist results or clear a lease owned by another worker.

Real subprocess kill tests cover pending-reservation durability, measured retry usage,
no duplicate version and zero dispatch when the retained charge leaves insufficient
budget. Separate-session pause/cancel, lease transfer and transport failure tests pass. A real SDK
HTTP transport fixture returns 500 and verifies exactly one request, with retained
unknown cost. Tenant-owned paginated /usage, metrics and build details separate observed
cost estimates from unresolved reservations; the build page labels reservations.
Connection permission checks now refresh previously loaded state, and a two-session
revocation test verifies denial. Migration 0005 preserves existing recorded usage;
populated upgrade/downgrade/re-upgrade tests and drift checks pass on SQLite/PG.

Final checks: Ruff; 56 SQLite tests passed (4 PostgreSQL-only skips); all 60 PostgreSQL
tests passed; strict TypeScript; 2 Vitest tests; existing complete browser journey;
optimized Docker builds; rebuilt API/worker/web/PG/Redis health, dashboard and usage
route checks. Browser coverage does not yet exercise the new reservation notice itself.
No actual provider credentials or production writes were used.

Remaining: durable evaluation/rubric/deployment provider accounting with safe approval
transactions and billing reconciliation; broader custom connector workflow evidence
and build redirection; secret/private-data and DNS/streaming hardening; memberships,
pagination, mobile/accessibility; full acceptance audit. The complete goal stays active.


2026-10-09 immutable build redirection milestone verified: the build page can save a
revised configuration with a reason and expected current version. The server creates
an immutable version, invalidates the prior worker lease and restarts evaluation.
Historical evaluations/iterations remain; old scorecards and pending proposals are not
reused for the revised objective. Global elapsed time, cost, iteration count and budgets
are retained; an exhausted iteration budget rejects redirection. Tenant ownership,
writer/admin policy boundaries, capability scope and mandatory guards are enforced.
Version creators serialize numbering on the tenant-owned agent row.

Behavioral tests exercise a real failed baseline, redirection, fresh passing evaluation
and held-out readiness while preserving old evidence/configuration. Repeated stale
requests, terminal builds, exhausted iterations, viewers, foreign tenants and removed
guards are rejected. An SDK contract request that returns after redirection records its
observed usage but cannot overwrite the new checkpoint or create another stale version.
The UI identifies the current candidate and filters progress to its current evaluation.

Browser verification caught an old false-positive locator matching a static READY stage
label; both journeys now wait on the actual accessible Build status indicator. The
stricter flow also exposed /auth/me consuming credential-attempt quotas and protection
responses lacking CORS headers. Profile reads now use the normal API limit; login,
registration and demo credential limits stay unchanged. CORS wraps rate protection;
429/503 responses retain security headers. A test verifies repeated profile reads do
not exhaust credential attempts and a real 429 response remains browser-readable.

Final checks: bash scripts/test.sh passes (Ruff, 60 SQLite tests and 4 PG-only skips,
strict TypeScript, 2 Vitest tests, both full browser journeys); all 64 PostgreSQL tests
pass. Migration drift checks pass on both databases. Optimized Docker images build;
rebuilt API/worker/web/PG/Redis health, dashboard and redirect route checks pass.
No live OpenAI credentials or production writes were used. The full goal stays active.

Next: general custom connector workflow/proposal-review browser evidence; durable
provider accounting for evaluation/rubric/deployment; secret/private-data and transport
hardening; memberships, pagination/mobile/accessibility and final acceptance audit.


2026-10-09 credential-boundary milestone verified: field-name filtering is extended to
known credential values, including ordinary text fields/dictionary keys and common URL,
JSON and base64 encodings. Credential JSON/DSNs contribute password values and Basic-auth
combinations. Filtering is tenant-scoped and covers global API/signing/encryption keys.
Model instructions/schemas/inputs, tool responses, runtime outputs, execution events,
factory role payloads, optimizer evidence, rubric payloads/grades, imported state and
browser serialization use the boundary. Queued input/idempotency comparisons use the
same safe representation. Authorized external receipts are sanitized before persistence.
Server-owned has_secret flags remain booleans.

Revocation archives ciphertext in an internal redaction-only table, clears active
credentials and marks the connection revoked. This preserves historical filtering
without granting dispatch or changing immutable historical configurations. Repeated
revocation is idempotent. No model, browser or adapter can retrieve the archive through
an API. Migration 0006 adds the tenant-owned table and passes drift/populated migration
checks. See docs/SECRET_BOUNDARIES.md for the tested scope and remaining limitations.

Adversarial fictional-credential tests inspect real SDK transport inputs/tool results,
an intentionally secret-bearing provider output, persisted events/browser rows,
authorized mocked adapter receipts, ordinary/encoded/key occurrences, tenant isolation
and post-revocation history. They do not execute a live model or production connector.
Final checks: bash scripts/test.sh passes (Ruff, 64 SQLite tests plus 4 PG-only skips,
TypeScript, 2 Vitest tests, 2 complete browser journeys); all 68 PostgreSQL tests pass.
SQLite/PG migration upgrades and drift checks pass; optimized Docker images rebuild;
API/worker/web/PG/Redis health and dashboard checks pass. No live credentials were used.

Remaining: resource-specific private-field minimization and unknown-data policies;
streaming/DNS/SSRF and production runtime hardening; durable evaluation/rubric/runtime
provider accounting; broader workflows/proposal review, memberships/pagination/mobile
and full acceptance audit. The full goal stays active.


2026-10-09 REST response-bound milestone verified: HTTP response bodies now stream
with independent 2 MB wire/decoded limits. Oversized advertised lengths reject before
reading; chunked responses stop as soon as the limit is exceeded. Gzip/deflate decoding
uses bounded output rather than HTTPX's full automatic decompression. Unknown encodings,
truncated compressed streams and trailing compressed data reject. Successful responses
still parse actual JSON through the registered REST connector.

The HTTP request/retry/body phase has a 15-second total deadline as well as transport
timeouts. GET/HEAD may retry HTTP 429 twice, with finite capped delays and closure of
discarded bodies before waiting. Write methods dispatch once, preventing automatic
retransmission of an ambiguous approved operation; runtime reconciliation remains the
existing recovery boundary. DNS validation occurs separately and needs further pinning
and deadline work; this does not establish whole-platform egress security.

Tracked real HTTPX stream fixtures verify zero reads for rejected length/encoding,
early termination of oversized bodies, closure, gzip expansion rejection, valid gzip
and deflate, truncated payload rejection, read-only retry behavior, zero body consumption
for 429 and real async deadline cancellation of a trickling response. No score overrides,
actual provider calls or production writes were used.

Final checks: 74 SQLite tests passed (4 PG-only skips), all 78 PostgreSQL tests passed;
Ruff, strict TypeScript, 2 Vitest tests and both complete browser journeys passed.
SQLite/PG migration drift checks pass; Docker images rebuild and API/worker/web/PG/Redis
health/dashboard checks pass. Integration documentation now states streaming limits,
write retry policy and retired-credential handling accurately.

Remaining: DNS rebinding-safe connection pinning and other transport bounds; generic
private-field minimization and production/security audit; durable evaluation/rubric/
deployment provider accounting; broader workflows/proposal review and remaining UX.
The full goal stays active.


2026-10-09 HTTP connection-pinning milestone: REST and MCP now use an origin-scoped
HTTP Core network backend. Resolution occurs asynchronously inside the connection
deadline; every DNS answer must be a public, non-transition, unscoped address. The socket
receives a numeric IP, preventing a second hostname resolution from changing the
destination. HTTP Host and verified TLS SNI/certificate identity retain the original
approved hostname. Cross-origin requests, SNI overrides, environment proxies, redirects
and Unix sockets cannot bypass the transport. Safe connection fallback selects only
already-validated IPs and does not retransmit an HTTP request. A timed-out resolver may
finish its OS thread later but cannot open a socket after cancellation.

The installed MCP 2 SDK needs native httpx2 transport/stream classes and snake_case
tool attributes; real SDK discovery exposed and verified the previous attribute bug.
Dependencies now declare the tested HTTP Core/MCP/httpx2 APIs. Both HTTPX clients map
body-phase failures to their native errors and retain stream closure.

Behavioral tests exercise rebinding between preflight/connect, numeric socket addresses,
mixed public/private DNS rejection, private/metadata/transition/scoped destinations,
DNS cancellation, exact origins, proxy disablement, native MCP transport and body errors.
An owned local TLS server verifies actual handshake/hostname rejection and actual MCP
SDK initialization, tool discovery and invocation with a fictional bearer token. Its
loopback socket mapping and test trust root are injected fixture dependencies only;
production configuration exposes neither. These are network/SDK contracts, not live
OpenAI or external-provider execution. No production writes were performed.

Final checks: 92 SQLite tests passed (4 PG-only skips), all 96 PostgreSQL tests passed;
Ruff, strict TypeScript, 2 Vitest tests and both complete browser journeys pass. Both
database migration drift checks pass. Optimized Docker images rebuild; API/worker/web/
PG/Redis startup and API health/dashboard HTTP checks pass. Three final mixed-DNS/body
tests were added after the first full run, then both complete backend suites reran.

Remaining: MCP stream/result-size bounds, email/Postgres transport limits, broader
private-field minimization and production/security audit; durable evaluation/rubric/
deployment provider accounting; broader workflows/proposal review and remaining UX.
The complete goal stays active.


2026-10-09 MCP response-budget milestone: every MCP client session shares separate
2 MB wire/decoded budgets across initialization, pagination, JSON and open SSE responses.
Gzip/deflate decoding uses a positive output cap before HTTPX2 or SDK parsing; invalid
lengths/encodings reject before reads, oversized streams stop early, completed compressed
bodies reject truncation/trailing data, and failed streams close. After budget exhaustion,
another stream cannot pass max_length=0 to zlib and trigger unlimited decompression.
Decoded headers are normalized to prevent a second native automatic decoder.

Discovery stops at 10 SDK pages and automatic tool-call retries remain disabled.
Initialization/discovery and initialization/tool execution have a 15-second deadline.
The transport also applies a shared lifetime deadline to headers, body reads and later
requests: cleanup cannot dispatch after expiry. Read timeout scopes end before yielding
to consumers, preserving async generator cancellation ownership.

Tests use tracked actual HTTP Core response streams through the native HTTPX2 transport:
zero reads for invalid headers, early oversized-body termination, bounded gzip expansion,
valid identity/gzip/deflate, truncated/trailing compression, shared open-stream budgets,
post-exhaustion decompression and trickle/expired-cleanup cancellation. The actual SDK
TLS fixture passes compressed JSON and compressed SSE tool results, rejects a gzip bomb
without repeating tools/call, cancels a trickle and stops malicious pagination at exactly
10 pages. No live model/provider credentials, metric overrides or production writes.

Final checks: 112 SQLite tests passed (4 PG-only skips), all 116 PostgreSQL tests passed;
Ruff, strict TypeScript, 2 Vitest tests and both browser journeys pass. Both database
migration drift checks pass. Optimized Docker images rebuild; API/worker/web/PG/Redis
startup and API health/dashboard HTTP checks pass. The final read-loop adjustment avoids
holding timeout scopes across generator yields and passes all 23 focused MCP tests;
the updated API/worker images were rebuilt afterward.

Remaining: email/Postgres transport bounds, private-field minimization and production/
security audit; durable evaluation/rubric/deployment provider accounting; broader workflows,
proposal browser review, memberships/pagination/mobile/accessibility and final acceptance.
The complete goal remains active.


2026-10-09 durable rubric-accounting milestone verified: independent read-only grading
commits a pending UsageRecord/run reservation before SDK dispatch. Build-funded calls
link both run/job and charge the build; observed usage settles its reservation, while
failed/timed-out requests retain uncertain charges without inventing observed tokens or
billing. A real killed grading process leaves a durable pending charge, and worker
recovery marks it uncertain without refunding it. Insufficient remaining budget blocks
retry before provider dispatch. Hidden provider HTTP retries are disabled.

Run metrics and scorecards keep observed cost and reservations separate. Build-funded
known run costs are charged once, with a migration-compatible marker for historical
completed results. Manual retries preserve old unknown reservations while using genuine
remaining budget; reservations count toward promotion cost ceilings and cannot prove
measured cost savings. Grading failures keep the check pending and preserve deterministic
failures; over-budget responses still persist actual observed usage.

Returning graders preserve pause/cancel, transferred leases and immutable redirection.
The worker abandons its stale trial result while retaining the observed charge. Manual
grading rereads the pending result after I/O: interleaved calls retain both charges but
publish one grade. The lease extension uses the bounded grading timeout, rather than a
longer whole-build duration. Grading hooks commit only evaluation/read-only state and
must not be reused for production tool/approval transactions.

Sixteen new behavioral tests cover separate-session pre-dispatch visibility, settlement,
unknown charges, actual SDK HTTP failure without retries, excessive reported usage,
process kill/recovery budgets, worker checkpoint charging, user controls, manual retry
history/concurrency and cost-policy handling. Local SDK models/transports are explicitly
fictional provider contracts, not live OpenAI calls. No score override or production write.

Final checks: 128 SQLite tests passed (4 PG-only skips), all 132 PostgreSQL tests passed;
Ruff, strict TypeScript, 2 Vitest tests and both browser journeys pass. SQLite/PG drift
checks pass; optimized Docker images rebuild and API/worker/web/PG/Redis startup plus
API health/dashboard HTTP checks pass. Engineering/evaluation/factory documentation and
the acceptance roadmap state the accounting boundary and remaining gaps.

Remaining: durable evaluated-agent/deployment provider accounting, broader custom
workflows and proposal browser review, email/Postgres transport and private-field
hardening, memberships/pagination/mobile/accessibility and final acceptance audit.
External OpenAI/provider credentials remain absent. The complete goal stays active.


2026-10-09 evaluated-agent accounting milestone verified: live evaluation execution
uses durable evaluation_agent UsageRecords linked to its run and optional build job.
Reservations commit before SDK dispatch, settle to observed reported usage, and retain
unknown charges on errors/interruption. Provider HTTP retries are disabled. Model/tool
boundaries recheck build stage and lease ownership before further tool dispatch. Observed
usage is retained even when returning responses lose ownership, while stale trials do
not create evaluation results or overwrite user pause/cancel decisions.

Accounting checkpoints are restricted to isolated/replayed/authorized read-only
evaluation. Passing a build job into production execution rejects before dispatch.
Normal deployment/approval transactions do not use these commits. Runtime result metrics
retain the ledger's reservation/accounted fields and measured duration; worker checkpoints
do not add settled costs again. Grading continues to use its independent durable role.
Recovery marks abandoned evaluation-agent requests uncertain and their orphaned execution
failed with InterruptedProviderCall. The unknown charge remains against the build budget;
insufficient residual budget rejects a fresh request before dispatch.

Eleven new tests exercise the real SDK registered-tool loop with an explicitly local
provider contract, separate-session pending-record visibility, settlement, known tool
outputs, zero production mutations/approvals, pause/cancel/lease transfer before tools,
actual HTTP failure without retry, standalone evaluation accounting, worker checkpoint
charging and production-boundary rejection. A real killed evaluation process proves
durable unknown usage, orphan status and recovery-budget behavior. Reported fixture tokens
are provider-contract evidence, not live OpenAI execution or billing. No score override.

Final checks: 139 SQLite tests passed (4 PG-only skips), all 143 PostgreSQL tests passed;
Ruff, strict TypeScript, 2 Vitest tests and both browser journeys pass. SQLite/PG migration
drift checks pass. Optimized Docker images rebuild; API/worker/web/PG/Redis startup and
API health/dashboard HTTP checks pass. Engineering/factory/evaluation/acceptance documents
and the roadmap state the implemented boundary and remaining gaps accurately.

Remaining: durable deployment/production provider accounting with safe approval/tool
transaction boundaries; broader custom workflows/proposal browser review; email/Postgres
transport and private-field hardening; memberships/pagination/mobile/accessibility; full
acceptance audit. External credentials remain absent. The complete goal stays active.


2026-10-09 production approval-staging milestone verified: connector write tool calls
allocate a stable approval ID and stage the request in execution context, without
attaching it to the SQLAlchemy session. The tool response labels it staged. A validated
final agent result publishes pending approvals with its decision checkpoint. Invalid
final output, subsequent provider failure and timeout do not publish a request, even
when an interim execution-event checkpoint commits. This closes a prerequisite safety
boundary for future durable production model accounting; the deployment ledger itself
is still incomplete.

Approval dispatch rejects queued/running/failed executions. Authorized administrators
can reject stale requests without applying them. Existing tenant, membership, immutable
contract, deployment and explicit-write checks remain in the normal resolver. A valid
staged request reaches the adapter only after explicit human approval.

Ten new tests exercise actual multi-turn SDK write requests and a deliberately committed
interim checkpoint, inspect another database session, and verify valid versus invalid,
failed and timed-out final results. They also cover approval/rejection across each unsafe
execution status. Only a clearly fictional mock email adapter runs after approval; no
external production write or actual live provider was used, and no score was overridden.

Final checks: 149 SQLite tests passed (4 PG-only skips), all 153 PostgreSQL tests passed;
Ruff, strict TypeScript, 2 Vitest tests and both browser journeys pass. SQLite/PG migration
drift checks pass; optimized Docker images rebuild and API/worker/web/PG/Redis startup
plus API health/dashboard HTTP checks pass. AGENTS.md, the roadmap and integration docs
describe the staging boundary and leave production accounting explicitly outstanding.

Remaining: per-model deployment ledgers/lease/authorization checkpoints, unknown charges
retained inside queue reservations, atomic final settlement and interruption recovery;
broader custom workflows/proposal browser review; email/Postgres transport and private
field hardening; membership/pagination/mobile/accessibility; full acceptance audit.
The complete goal stays active.


2026-10-09 queued deployment accounting milestone verified: live deployment execution
persists a run-owned deployment_agent UsageRecord before every model dispatch. Calls
reserve within the existing whole-invocation allocation; observed tokens settle to
configured cost estimates while provider failures/termination retain unknown charges.
Recovery marks abandoned pending calls uncertain and counts historical usage/reservations
against the invocation ceiling. Queue completion releases unused allocation while retaining
unknown charges in Deployment.reserved. Hidden SDK HTTP retries are disabled.

Model/tool checkpoints recheck tenant/invocation associations, current membership,
approved pinned version, active deployment and lease owner. Returning revoked workers
retain observed charges and cannot dispatch further tools or publish approvals. The final
checkpoint checks updated cost/lifetime limits; final result, staged connector/fixture
approvals and queue settlement commit together under queue/deployment locks. Fixture
approval IDs are allocated without an early attachment to the session.

Late responses after a successor has completed settle their retained reservation into
observed deployment spending without overwriting the successor result or creating another
approval. Ten new behavioral tests cover separate-session pre-dispatch visibility,
pause/membership revocation/version unapproval/budget reduction, lease transfer, provider
failure, actual SDK HTTP failure without retries, real process kill/recovery and a nested
successor followed by the stale model response. Models/transports are explicitly local
provider contracts, not live OpenAI or external production execution. No scores were
invented and no production side effect was executed.

Final checks: 159 SQLite tests passed (4 PG-only skips), all 163 PostgreSQL tests passed;
Ruff, strict TypeScript, 2 Vitest tests and both browser journeys pass. SQLite/PostgreSQL
Alembic checks show no drift. Optimized Docker images rebuild; API/worker/web/PG/Redis
start, API reports healthy labeled demo mode and dashboard returns HTTP 200.

Remaining: standalone production/preview accounting and authorization checkpoints;
broader multi-turn connector and residual-budget/concurrent-policy audit; custom workflows
and proposal browser review; email/Postgres transport/private-field hardening;
memberships/pagination/mobile/accessibility and complete requirement-level audit.
External credentials remain absent. The complete platform goal stays active.


2026-10-09 proposal browser review milestone verified: the build page shows scenario
names/splits/critical flags/assertion counts derived from the editable plan and reports
invalid JSON inline with accessible field/error associations. Administrator correction
and acceptance is verified end to end, including persisted cases and actual subsequent
isolated execution/grading. Invalid JSON leaves review pending; an attempted live-access
grant returns 403 and imports no cases. Correcting the fictional Tomatoes expectation
from 901 to 900 cents imports six scenarios; independent held-out execution passes two
cases. Repeated acceptance returns 409 and reload preserves the completed review.

The disposable browser database prepares proposals through the real Test Designer SDK
and worker with an explicitly local Model fixture, not a network model. The helper only
accepts the E2E temporary SQLite path. It seeds no scores or evaluation results; the demo
worker executes actual fixture tools and graders after human review. No test endpoint
was added to the application and no external production side effect was performed.

The expanded journey exposed a real frontend request storm: per-event stream cache
invalidation exhausted the existing API limit and left an accepted proposal on screen.
Build streams now coalesce refreshes into a 1.5-second window while retaining every
cursor update and canceling pending work on unmount. All three browser journeys verify
zero HTTP 429 responses. API limits were not raised or disabled. Docker contexts now
exclude browser traces/reports and TypeScript cache artifacts.

The execution-entry-point audit corrected the roadmap: all public production invocation
routes already enter the durable queue. Direct execute is an internal helper, not a
standalone production/preview endpoint. Any future public entry must retain durable
accounting and current authorization. Multi-turn/residual-budget/concurrent-policy audits
remain open; this correction does not claim the broader security audit complete.

Current scoped checks: Ruff; 13 factory-role tests on SQLite and 13 on PostgreSQL;
strict TypeScript; 2 Vitest tests; all three browser journeys; shell syntax/diff checks.
Optimized Docker images rebuild and API/worker/web/PG/Redis start; API health reports
labeled demo mode and dashboard returns HTTP 200. The unchanged backend's last full
suite remains 159 SQLite tests plus 4 PG-only skips, and all 163 PostgreSQL tests.

Remaining: broader custom connector workflow journeys; deployment concurrency/budget
contracts; email/Postgres transport/private-field hardening; memberships/pagination/
mobile/accessibility, templates B/C browser evidence and full requirement-level audit.
Actual OpenAI/provider credentials remain absent. The complete platform goal stays active.


2026-10-09 workspace access milestone verified: administrators can create/revoke
email-bound invitations, change member roles and remove membership from Settings.
Membership and invitation collections have server/UI pagination. Recipients can register
or sign in, accept the one-time code and switch between authorized workspaces. Acceptance
returns a session for the joined workspace; removal/downgrade affects already-issued
sessions because every request resolves current membership. Workspace switching reloads
the application, and sign-out/sign-in clears cached query data across accounts.

Invitation codes have 256-bit randomness, are returned once for private delivery and
are stored only as SHA-256 hashes. Raw codes/hashes are omitted from lists and audits;
no automatic email or external write was performed. Acceptance requires a matching
signed-in email, pending/unexpired grant and a still-authorized inviting administrator.
Replacement invitations revoke old grants. Existing memberships cannot be upgraded by
an invitation. Self-admin demotion/removal is rejected. PostgreSQL organization locks
serialize administration/acceptance, followed by a fresh actor-role check. Concurrency
tests prove single invitation consumption and one remaining authorized administrator
under competing demotions. The account-registration flow does not claim independent
email verification; private code possession is the invitation grant authority.

Migration 0007 adds organization_invitations without changing existing membership or
business/evaluation history. SQLite and PostgreSQL upgrade/drift checks and populated
migration upgrade/downgrade tests pass. OpenAPI and shared TypeScript contracts include
membership/invitation/switching requests. Browser HTTP 204 handling now supports successful
removal without a JSON parsing error. Invitation expiry responses explicitly retain UTC.

Eleven new backend cases cover hash-only storage, one-time/email-bound consumption,
expired/revoked/replaced/inviter-demoted grants, existing-role protection, tenant/admin
boundaries, pagination, session revocation and switching; two run only on PostgreSQL for
actual row-lock concurrency. A fourth browser journey signs up a teammate, accepts a
reviewed role, switches both workspaces, downgrades/removes membership, verifies the old
token is denied and signs into the surviving workspace with cleared cached data.

Final full checks: 168 SQLite tests passed (6 PG-only skips); all 174 PostgreSQL tests
passed; Ruff, strict TypeScript, 2 Vitest tests and all four browser journeys pass with
zero HTTP 429s. Scoped membership checks pass again after UTC/non-admin assertions.
Optimized Docker images rebuild; API/worker/web/PG/Redis start, API health reports
labeled demo mode and Settings returns HTTP 200. Access/engineering/acceptance documents
and the roadmap record the implemented behavior and remaining gaps.

Remaining: broader arbitrary connector workflow and deployment concurrency/budget
contracts; email/Postgres transport/private-field hardening; broader collection pagination,
mobile/accessibility, templates B/C browser coverage, runbook and full acceptance audit.
External model/provider credentials remain absent. The complete platform goal stays active.


2026-10-09 primary collection pagination milestone verified: agent suite and deployment
endpoints now accept validated offset/limit parameters with deterministic ordering, bounded
pages and tenant ownership checks. Published OpenAPI includes the new parameters.
Frontend agent library, project/connection selectors, integration/approval lists, versions,
evaluation history/scenarios and deployment history expose Load more controls. Paged
queries use separate cache keys, preserve loaded options and remove duplicate IDs.
Polling scales with loaded page count, limiting refresh request growth. Buttons inside
creation forms explicitly use type=button, so traversal cannot submit a new agent.
Candidate versions refresh during builds to show worker-created immutable revisions.

A separate disposable fixture tenant contains 53 projects, discovered fixture connections
and actual baseline AgentSpecs created through the builder/persist-version functions.
No evaluation score or result is seeded. The fifth browser journey reaches an older agent,
loads the second project/connection pages, selects the oldest project/connection and
creates a real agent that completes isolated evaluation/improvement to ready for review.
All five browser journeys pass with zero HTTP 429 responses. A unit check verifies
pagination replacement preserves existing query filters. API tests traverse 53 suite/
deployment rows, verify non-overlapping stable pages and boundaries, reject oversized/
negative parameters and deny another tenant's access.

Initial backend verification found two test setup/assertion defects and they were fixed
before the final rerun. The new suite fixture now preserves the existing authored suite
and dependent cases instead of attempting a foreign-key-blocked delete. An older imported-
mapping test assumed the first randomly ID-ordered product had a particular stock value;
it now checks the entire business snapshot before/after evaluation, strengthening proof
that mapped isolated evaluation leaves production fixture state unchanged.

Final checks: 170 SQLite tests passed (6 PG-only skips); all 176 PostgreSQL tests passed;
Ruff, strict TypeScript, 3 Vitest tests and all five browser journeys pass. SQLite/PG drift
checks show no migration changes. Final optimized Docker images rebuild and API/worker/
web/PG/Redis start; API is healthy in labeled demo mode and dashboard returns HTTP 200.
Engineering/README/acceptance/roadmap documents reflect this scope without calling the
complete collection or platform acceptance audit finished.

Remaining collection work includes secondary audit/build-trace/trigger/invocation lists,
suite selection UX and embedded/detail/derived-result resource bounds. Other remaining
work includes custom connector workflows, deployment concurrency/budget contracts,
email/Postgres transport/private-field hardening, mobile/accessibility, templates B/C
browser evidence, runbook and full requirement-level audit. External provider credentials
remain absent. The complete platform goal stays active.

## 2026-10-10: Builder harness, phases 0 to 2 (search loop, evidence, bundle)

Scope follows the v2 builder proposal. This entry covers the search-loop fixes, the
measurement additions, the bundle fields and the tool-using optimizer. Research, the
sandbox, generated tools and connection proposals are separate later entries.

A reproducing test first proved a defect in the existing loop: after a rejected candidate,
`checkpoint["version_id"]` stayed on it and the next optimizer call edited the rejected
version. The loop now branches from the best-known version and shows the optimizer that
version's failures. The optimizer also receives an attempt history (hypothesis, outcome,
regressed cases), passing development examples for contrast, and each failure's tool
sequence. A boundary test asserts only development-split case names reach the payload.

Promotion keeps its binary gates and adds a noise guard that is active only when repeated
trials disagree: the paired per-case improvement must exceed one standard error estimated
from those trials. Single-trial and deterministic suites behave exactly as before.
Scorecards add `graded_score` (partial credit over case-specific checks, zero on a safety
or approval violation), `case_rates` and `case_names`. The line-item arithmetic check now
runs only for outputs that carry `lines`, so it can no longer pass vacuously.

AgentSpec gains three builder-authored fields that the runtime executes: `examples` and
`tool_notes` are rendered into the model instructions, and `verifiers` (closed vocabulary:
required, one_of, range, sum_equals, schema) run before a result is returned. A failed
verifier earns one bounded repair pass in live mode; a persistent failure sets
`needs_attention` and is never staged for approval. Version persistence rejects an example
that cites or reproduces a regression or held-out case, and tool notes for tools outside
the version.

The live optimizer is now an SDK agent with four read-only tools (list_cases, get_case,
get_tool_contract, get_attempt_history) and returns a typed `SpecPatch`. The tools enforce
tenant, suite and development-split by case identity and filter tenant credential values;
refused reads are audited in an `optimizer_investigation` event. The patch model has no
locked fields, and the applied result is still scope-checked. A proposal that breaks the
contract (locked field, protected example, tool loop past the turn limit) is recorded as a
rejected attempt and no longer fails the build. `Budget.candidates_per_round` (default 1)
enables rounds of several proposals from the same parent, each given a different strategy;
a new SCREENING state runs each candidate on the parent's failing development cases plus
a sample of passing ones, prunes any that fix nothing or break something, and fully
evaluates survivors in rank order. Screen runs have status `screen` and are never
promotion evidence. `BUILDER_MODEL` selects the factory-role model, defaulting to
`OPENAI_MODEL`.

Two defects were found and fixed while verifying. A persisted verifier could not be
reloaded because it serialised `expected_schema` but accepted only the `schema` alias.
Checkpoint edits made after an autoflush were invisible to change detection when the same
dict object was reassigned; a worker-driven restart test exposed it, and checkpoints are
now always stored as fresh copies.

Checks: Ruff; 199 SQLite tests passed (6 PG-only skips); all 205 PostgreSQL tests passed.
Not verified: any real provider response. The optimizer, investigation and repair paths
are exercised through the real SDK loop with local scripted provider transports only, so
whether a real model writes useful patches remains unmeasured. Parallel trial execution,
rerun confirmation and a rotating held-out set are not implemented. Known quirk left in
place: an assertion on path `status` reads the run status and shadows an output field of
that name.

## 2026-10-10: Builder harness, phases 3 to 7 (research, sandbox, code, connections, release)

Full description: docs/BUILDER.md. The invariant "no arbitrary generated code" in AGENTS.md
and the matching sentence in ARCHITECTURE.md were amended by explicit decision: builder-
written code is now allowed, only inside the sandbox and only under the rules listed there.

Open-web research (`factory/research.py`, off unless `RESEARCH_ENABLED=true`) is a separate
agent run that receives only a question. The question, search queries and every URL,
including redirect targets, pass an outbound screen built from tenant credential values and
markers of the evidence the builder has seen. Fetches reuse the pinned public-address
transport with a new origin-scoped client per hop, https and the default port only, bounded
bodies and a fetch budget. Researcher model calls are reserved and settled under their own
role. Sources are recorded on the candidate and in the hypothesis event.

The sandbox service (`services/sandbox`) runs builder-written tools. The compose service has
no network, a read-only root, no capabilities, an unprivileged user and resource limits, and
is reached over a Unix socket on a 1 MB tmpfs volume where it is the server. A capability
call stops the run and reports the request; the worker performs it through
`ExecutionContext.invoke` and re-runs with the result recorded, so the existing tenant,
contract, approval and redaction checks apply and writes are staged, never executed.
Generated tools are stored in the spec, pinned by sha256 and re-checked before each run.
`POST /versions/{id}/approve` refuses a version with unreviewed code until the request
acknowledges each hash. Without `SANDBOX_SOCKET` generated tools fail closed.

Connection proposals (`factory/proposals.py`, migration 0008) are inert drafts created by
the builder, manually, or by a deterministic OpenAPI 3 import. Approval is administrator-
only, requires the exact hosts to be repeated, and is the only place a credential exists or
a vendor is contacted; a failed activation keeps nothing. Attaching creates a fresh version
and restarts build evidence as a redirection does.

Feedback and release (`factory/release.py`): deployed runs that were rejected, needed
attention or failed are listed as candidates; an administrator can turn one into an
evaluation case with explicit data-use authorization and their own expected result; a shadow
run replays recent real inputs through a candidate in evaluation mode; a dossier gathers
reach, code review state, evidence, provenance, the shadow report and open items; and the
optimizer receives a tenant-scoped playbook of previously promoted hypotheses.

Defects found and fixed during verification:

- `PermissionError` is a subclass of `OSError`, so the sandbox client's unreachable-service
  handler reported a denied capability as an outage instead of a safety violation.
- The OpenAPI importer's cycle guard counted nesting depth, not reference hops, and replaced
  ordinary nested values with a placeholder.
- A run could leave empty files in the sandbox temp filesystem for a later run to read. The
  service now removes everything a run leaves, and kills the run's whole session.
- Two of the first isolation checks were wrong rather than the sandbox: kernels expose
  inactive tunnel devices in every namespace, and the base image's `GPG_KEY` is a public
  fingerprint. The checks now test "no active interface but loopback" and an exact
  environment allowlist.

Checks: Ruff including services/sandbox; 311 SQLite tests passed (6 PG-only skips); all 317
PostgreSQL tests passed; migration 0008 upgrade, downgrade, re-upgrade and autogenerate
drift check on SQLite and PostgreSQL; 36 container isolation checks in
`scripts/test-sandbox.sh` against the real image; a containerized end-to-end run on a
throwaway compose project where the worker executed a generated tool through the sandbox
socket with a brokered capability; strict TypeScript; 3 Vitest tests; production web build.

Browser journeys: 4 pass, 2 fail. The new `builder.spec.ts` passes: dossier, approval,
deployment, a case from a real run, a read-only shadow comparison, the code-review screen
and a connection draft whose approval stays disabled until the right host is typed. The two
failures, `factory.spec.ts` and `pagination.spec.ts`, were reproduced on a clean checkout
containing only the uncommitted build-timeline pagination edits and none of this work: the
timeline now loads 50 events per page, so "requirements analyzed" and the first failing
cases are not on screen. With that single assertion removed from a temporary copy of each,
both journeys pass in full on this work. They are left for the pagination change to resolve.

Not verified: any real model response; a real search provider; a real vendor API; a
hardened production sandbox runtime beyond the documented Docker settings. Not built:
parallel trial execution, rerun-to-confirm promotion, a rotating held-out set, non-REST
proposals, path parameters in the REST connector, and third-party packages for generated
tools.

## 2026-10-10: Search benchmark and browser journeys

`apps/api/benchmarks/search.py` runs whole builds on the real engine. With a seeded simulated
proposer drawing from two helpful, two useless and three harmful ideas, 30 builds per arm:
one candidate per round without history reached the target in 67% of builds at 244 trials;
with history 100% at 182 trials; three screened candidates with history 100% at 176 trials
and 4.37 full evaluations against 6.20. History is the large effect. Screening saved about
30% of full evaluations but only about 3% of trials on this small suite. This measures the
loop, not model quality. The live mode, one-shot optimizer against the harness with the real
provider, is implemented and refuses to run without a key; it has not been run because no
provider key exists in this environment.

The two failing browser journeys are fixed. Cause: when a build finishes, the paged build
timeline refreshes on a poll, so its "Load more" control appears about two seconds later.
`pagination.spec.ts` checked for the control once and gave up, and its loop also exited
while a page was loading because the button then reads "Loading…". `factory.spec.ts` had not
been updated for the paged timeline. Both now wait for the control, then load every page by
waiting for the shown count to change. This was a test-side defect; the timeline's short lag
after completion is unchanged.

Checks: Ruff including apps/api/benchmarks; 314 SQLite tests passed (6 PG-only skips); all
320 PostgreSQL tests passed; strict TypeScript; 3 Vitest tests; all 6 browser journeys pass,
three consecutive runs; 36 sandbox isolation checks.

## 2026-10-10: Real-model runs on the OpenAI API

An earlier set of runs used a local model that happened to be installed on the development
machine. Those runs are withdrawn: a local model is not wanted for this project, and loading
it beside the Compose stack filled the host disk and hung Docker Desktop. The stack was
restored without rebuilding and the development database verified (schema at 0007, public
tables empty, no test schemas left behind). The code fixes those runs led to are kept and are
listed in docs/BUILDER.md; the numbers are not, and every result below is from the OpenAI API
with `gpt-5.5` as the builder.

Benchmark, builder isolated (agent executed deterministically), two builds per arm: the
one-shot optimizer reached the target with every held-out case passing in 2 of 2 builds, 64
trials, estimated builder cost 0.02. The harness as first built reached it in 0 of 2, with
182 trials and estimated cost 0.90. Cause: each proposal of a round was told which mechanism
to use, which pushed a capable model off the fix it would have chosen and into verifiers
that failed correct outputs. The round now leaves the first proposal unsteered and asks later
ones only to differ from the round so far. After that the harness reached the target in 2 of
2 builds, 79 trials, estimated cost 0.19. A further complete harness build with research
enabled reached the target; the builder read nine development cases, two tool contracts and
the attempt history, and all seven model calls were reserved and settled.

Directed exercises with the same model: research fetched https://example.com over the real
internet through the pinned transport and reported it correctly in 3 of 3 runs, with a
question containing customer data refused before any call; a model-written tool passed the
code policy, was pinned by hash and ran correctly in the host-run sandbox service in 4 of 4
attempts; a valid inert connection draft was produced in 4 of 4, with no connection created.

Further fixes from these runs: an empty `OPENAI_BASE_URL` once exported blanked the SDK's
base URL and broke every live call; tool notes keyed by tool name now resolve to the tool id
when unambiguous.

What this establishes: the builder works with a capable real model, end to end. What it does
not: that the harness is worth its cost. On this task it is not; the one-shot optimizer gets
the same result at about a tenth of the builder spend. The task has one obvious fix, so harder
task families are needed, and two builds per arm cannot compare arms.

Checks: Ruff; 328 SQLite tests passed (6 PG-only skips); all 334 PostgreSQL tests passed;
strict TypeScript; 3 Vitest tests; all 6 browser journeys.

## 2026-10-10: enterprise console and build inputs

The web app was restyled as a dense console: grouped navigation, breadcrumbs, a KPI strip, an
agents table, a build stage stepper and written-out form labels. The dashboard heading is now
"Overview".

Build inputs (docs/INTAKE.md). A build takes a task, business context documents and a source
of truth, and is refused without examples that have correct answers or a recorded statement
that none are needed. Datasets are uploaded or fetched from a public https address over the
pinned transport, parsed, cleaned and split in code; the builder sees a profile with
development rows and never a held-out row. Derived input and output schemas are pinned.
Context documents go to the architect, test designer and optimizer, and to paged investigator
tools, and never to the deployed agent. Custom agents may have no tools. A build that runs out
of rounds measures its best version on the held-out cases and reports the score while still
ending exhausted. The approval gate now requires development and held-out evidence;
regression cases are no longer required to exist.

Found while doing this: the browser created a new query cache on every navigation, so each
section change refetched everything, and every action refetched the signed-in user. With an
added journey the suite crossed the 500 requests per minute API limit. One cache per tab and
no identity refetch after unrelated actions brought the seven journeys to 464 requests with
no HTTP 429. A message raised just before a redirect is now kept for its few seconds across
the remount.

Live, on OpenAI with `gpt-4.1-mini` as agent and builder: one sentence of task plus the public
Banking77 test file (3,080 rows, 77 answers) went through the real endpoints and worker loop:
fetched, split 20 and 20, designed, three rounds (12, 12 and 13 of 20 on development), held-out
12 of 20 for both the first and the final version, 1.7 minutes, about 67,000 tokens. This
proves the path works on a real model. It does not show the builder improves an agent: the
sample is far too small and the round-three gain of one case is within noise. The run showed
that a tool-less agent's first instructions did not state its task; they now do.

Checks: Ruff; 366 SQLite tests passed (6 PG-only skips); all 372 PostgreSQL tests passed;
migration 0009 upgrade, drift check, downgrade and re-upgrade on SQLite and PostgreSQL; strict
TypeScript; 3 Vitest tests; all 7 browser journeys with zero HTTP 429s.

## 2026-10-10: real builds on gpt-5.5, and what they changed

Three live builds of a banking message router from one sentence and the public Banking77 test
file, `gpt-5.5` as builder and agent.

1. Failed at design: the architect's reply was cut off at a 4,000-token cap. Replies are no
   longer capped.
2. 60 rows to build from, 60 held back, 15.6 minutes: 0, 55 then 60 of 60 on the rows the
   builder read, 51 of 60 (85%) held back. The zero was a check the architect wrote that
   rejected correct answers.
3. The same after fixes, 12 minutes, about 4.90 dollars at 5 and 30 dollars per million input
   and output tokens: first version 50 of 60 read and 51 of 60 held back; the builder's
   version 57 of 60 read and 50 of 60 held back. The builder did not improve the agent on rows
   it had not seen. It fitted rules to the rows it could read, was scored on those same rows,
   and stopped after one round because they met the target.

A fourth run, with a selection split at 150/100/100, was stopped by the owner during its first
pass and has no result.

What was built in response (docs/RUNNING_BUILDS.md): a selection split the builder is scored
on and never reads, with a net-gain-beyond-chance rule and a second run of changed cases;
provider failures retried and never scored, then a pause that resumes; parallel live trials;
uncapped replies; per-model pricing with input, cached and output tokens; a budget check that
keeps room for the final held-out pass; idle time excluded from the time limit; early stop of
a uniformly failing pass; removal of checks that reject known answers, before and after a
pass; an example pool with similar-example selection; a confusion summary; the builder barred
from changing the agent's model unless it is listed; a BELOW_TARGET end state; hybrid mode;
dataset removal; the score required for approval set at creation; spend by role on the build
page; a resumable command-line runner.

Found by the tests: on PostgreSQL, cancelling a build during a parallel pass deadlocked. A
hook raised while holding the build row lock, the SDK awaited during cleanup, and every other
trial waited on the row forever. Hooks now commit before raising.

A small live run on `gpt-4.1-mini` (40/40/40, about 12 cents) was killed on purpose during
its first builder step and resumed from the kept database to the end: 31 of 40 read and 29 of
40 unseen for the first version; two later versions reached 37 and 32 of 40 on the rows the
builder read but 31 and 30 of 40 unseen, and were rejected as within chance; 28 of 40 held
back. This shows the machinery working on a real model. It does not show the builder adding
value: that needs the gpt-5.5 run at 150/100/100.

Checks: Ruff; 396 SQLite tests passed (6 PG-only skips); all 402 PostgreSQL tests passed;
migrations 0009 to 0011 upgrade, drift check, downgrade and re-upgrade on both; strict
TypeScript; 3 Vitest tests; all 7 browser journeys with zero HTTP 429s.


## PDF documents as input, and a first restaurant demo since removed (2026-10-11)

Built: `factory/documents.py` reads the text layer of a PDF with its layout, bounded in bytes,
pages and characters, and refuses a scan by file name and page; `POST /documents/text` returns a
PDF's text and stores nothing; `POST /agents/{id}/datasets/archive` takes a zip of one examples
file and the PDFs its cells name; context documents and the two upload forms accept them; whole
number columns of a delimited file are typed as integers; a request that mentions orders or
quotes with no connection is a custom agent, not a template. See docs/INTAKE.md.

The first demo, removed later the same day in favour of the real invoices below, was a supplier
invoice check on the public Northwind PDFs (830 orders, each
an invoice, a purchase order and usually a shipping order; Apache 2.0). One known error is
planted in a share of the packets by redrawing a document in the original layout; every answer
is recomputed from the finished PDFs before anything is written.

Live runs, local SQLite, hybrid mode, 60/40/60 split:

- `gpt-4.1-mini`: first version 56 of 100 scored, one change rejected, 24 of 60 held back. $0.17.
- `gpt-5.5`: the first version got 60 of 60 read, 40 of 40 unseen and 60 of 60 held back, so the
  build ended at its target with no improvement round. $7.43. Deployed, it then decided all 147
  invoices of the March and April 2018 batch correctly (32 of 32 problems held, no good invoice
  held, $16,014.39 of $16,014.39 in dispute found) through the production queue for $6.35.

What this does not show: the documents are digital, in one plain layout, and the rule is exact,
so the task is easy for a large model. It says nothing about scans, varied supplier layouts or
a real restaurant's invoices, and again the builder was not needed to improve anything. That
agent was built before number typing, so it returns the amount as text.

Checks: Ruff; 419 SQLite tests passed (6 PG-only skips); strict TypeScript; 3 Vitest tests.
Not run: the PostgreSQL suite and the browser journeys (the dev app was running), and there is
no browser test of the zip upload yet.

## Scanned documents, and real invoices from court records (2026-10-11)

Built: `factory/reading.py` reads scanned pages and photos through the model when
`DOCUMENT_READING` is on, with a `document_reader` usage record committed before each page, a
per-upload ceiling, a per-tenant cache keyed on the page image, waits on provider rate limits as
new accounted calls, and an immediate stop when the provider account has no credit. A page that
is a stamp over a page-sized image now counts as a scan instead of being read as its stamp.
Migration 0012. See docs/INTAKE.md and docs/SECRET_BOUNDARIES.md.

`demo/restaurant/` holds 101 real invoices (146 scanned pages) from three public court
exhibits, with answers verified by arithmetic and, for 60 of them, against the supplier's own
filed summary. Measured while labelling: 1,276 of 1,277 Gordon Food Service lines satisfy
quantity times price equals amount.

Not done: no build has run on the real set and the platform reader has not been run on it. The
provider account ran out of credit during labelling (about $27 spent this session), which also
left about 100 pages of the produce and Sysco exhibits unlabelled. Three real pages were read
correctly in a manual test of the same instructions; a dense sideways Sysco page was read with
errors.

Checks: Ruff; 426 SQLite tests passed (6 PG-only skips); strict TypeScript. Not run: PostgreSQL
suite, migration 0012 on PostgreSQL, browser journeys.

The Northwind demo files were deleted on 2026-10-11; `demo/restaurant/` is now the real set only.
The runs recorded above happened and are kept as history.

## The real-invoice demo run end to end on gpt-6-luna (2026-10-11)

Every role on `gpt-6-luna` (reader, agent, builder), local SQLite, hybrid mode, scan reading on.
Reading the 116 example pages cost $0.12 in all. The build on 86 real invoices (30/20/36) ended
at its 80% target on the first version: 30 of 36 held-back invoices fully right, 95% of fields,
for $0.05; no improvement round ran. Deployed, it read the 15 held-back Gordon Food Service
invoices (30 scanned pages) through the production queue and got all four fields right on all
15, including the 5 with a price rise, for $0.05 with reading.

Two earlier builds on 30 invoices gave 10 and 8 of 12 held back: on a set that small the score
swings. Misses seen were on the produce invoices, whose dates and numbers in the answer key have
no independent check. Found by the first real upload: PDFium crashed the API when pages were
drawn from several threads (now one document at a time), and a five-page invoice exceeded the
20,000 character field limit (now 60,000 for a document).

Checks: Ruff; 427 SQLite tests passed (6 PG-only skips). Not run: PostgreSQL suite, migration
0012 on PostgreSQL, browser journeys.

## Reading under builder control, table answers and the invoice view (2026-10-11)

Built: `spec.reading` (notes added to page transcription, questions answered from page images),
changeable by the builder and described to it only for agents with scanned requests; page images
of example documents kept (`document_pages`) so a version with its own reading settings has them
read again against the build budget; an investigator tool `ask_page` for development cases only;
`/documents/text` reads with a deployment's settings and can keep page images for a production
run. Table answers: an examples file may give a list of rows as a correct answer, graded row by
row (`factory/tables.py`, ops `rows_match` and `similar`), so a long invoice with one misread
line is not scored as nothing. The run page shows the scanned pages beside the answer, with each
line item set against the expected one. Migrations 0012 (extended) and 0013.

Measured on `gpt-6-luna` for every role, 88 real invoices (30/30/28):

- Four header-and-count fields, 95% target, builder with reading control: 21 of 28 held back.
  The builder questioned pages ten times and never changed the reading settings; none of its
  three revisions was kept. Every miss was on the two produce suppliers.
- Full extraction (five header fields and every line, 1,475 lines in the examples): 22 of 28
  held-back invoices right in every field and line, 96.9% of checks, on the first version; no
  improvement round ran because the build's target was set to 50%. Build cost $0.09.
- Batch, 15 held-back Gordon Food Service invoices, 372 lines: all 75 header fields right, 369
  of 372 lines right, 9 of 9 price rises found, none wrongly flagged, 13 of 15 invoices right
  throughout. $0.03 with reading.

Known gaps: approval and the keep-a-change rule still count whole invoices, which is too coarse
for table answers; the answer key's descriptions are a model's reading and are compared loosely;
fields the key cannot vouch for (terms, representative, addresses, pack size) are not extracted.

Checks: Ruff; 436 SQLite tests passed (6 PG-only skips); strict TypeScript. Not run: PostgreSQL
suite, migrations 0012 and 0013 on PostgreSQL, browser journeys.

## The customer side (2026-10-11)

Built: customer workspaces as organizations of their own, opened by a builder; installing a
deployed agent into one as a copy of its approved version; a `customer` role confined to the
portal in `security.principal`; the portal API (inbox, document with pages and corrections,
price watch computed in code, CSV export); channels (IMAP mailbox with a pinned TLS connection,
an inbound address with a hashed key, a results webhook through the pinned transport); a
Customers page on the builder side and the portal screens on the customer side. Migration 0014.
See docs/CUSTOMERS.md.

Run on `gpt-6-luna`: the invoice agent rebuilt as extraction only (19 of 28 held-back invoices
right in every field and line, 95.9% of checks, $0.07), installed in a demo customer workspace,
and all 60 Gordon Food Service invoices sent through the portal in date order: 60 processed,
$0.18 in the customer's own ledger. Price watch listed 17 rises; the answer key has 15 for those
invoices, and two of the 17 are one misread price (4.20 read where 42.00 was printed, or the
reverse), shown as a 900% rise.

Not verified: the mailbox reader against a real IMAP server, and webhook delivery against a
real endpoint; both are tested with stand-ins only. No browser tests for the new screens
(checked by screenshot). Checks: Ruff; 443 SQLite tests passed (6 PG-only skips); strict
TypeScript. Not run: PostgreSQL suite, migrations 0012 to 0014 on PostgreSQL, browser journeys.

## The invoice job end to end, and the owner's overview (2026-10-11)

Built on the customer side: automatic checks in code (`factory/payables.py`) that decide which
invoices need a person; approval singly, in bulk or automatically for clean ones; ledger
accounts per supplier and bills import files for Xero and QuickBooks Online; a second kind of
operation that reads supplier statements, reconciled against invoices received; upgrading the
agent behind an operation and reading unapproved documents again from stored pages; tax as a
recorded field; an Overview page for the owner that prints as a report. Migration 0015.

Run on `gpt-6-luna` in the demo customer workspace:

- Invoice agent rebuilt to record tax: 21 of 28 held-back invoices right in every field and
  line, 98.4% of checks, $0.07.
- All 60 Gordon Food Service invoices read again after the upgrade. Against the answer key:
  number, date, total and tax right on 60 of 60, and 1,225 lines recorded where the key has
  1,225. Before tax was recorded the checks set aside 24 of 60, every one for sales tax; after,
  they set aside 1, for a price a quarter of the last one paid.
- Price watch: 15 rises over 5%, the number in the answer key, costing $48.39 on $47,198 billed.
- Statement agent built on 72 statements drawn from the real invoice figures: 24 of 24 held
  back. On the one real statement (three scanned pages) it read 60 of 60 rows as the key has
  them. Reconciled: 59 agree, one the supplier lists was never received ($1,521.80), one on
  file is not listed.

What this shows and does not: the value in this data is entry and checking done without a
person, not money found. Price rises cost $48 in three weeks across ten locations. The export
files are untested against a live Xero or QuickBooks account. The statement examples are drawn,
not real, apart from the one. No customer has used any of it.

Checks: Ruff; 452 SQLite tests passed (6 PG-only skips); strict TypeScript. Not run: PostgreSQL
suite, migrations 0012 to 0015 on PostgreSQL, browser journeys. New screens checked by screenshot.

## Customer platform apart, purchasing dashboard, and the savings sums corrected

- Correction to the entry above: the invoice "never received ($1,521.80)" is in the court exhibit
  (document 427-5, pages 13 to 15), signed for. It had been left out of the demo set because its
  first reading did not add up, so the statement check reported it missing. `customer.py` now
  sends it in. The real statement reconciles 60 of 60, with one 2-cent sample invoice on file
  that the supplier does not list.
- "Same item, different price" compared prices across a week, which mostly caught the supplier's
  price moving mid-week. It now compares the same day only and leaves out a location that itself
  paid the low price. A line that is both a rise and a gap is counted once. Only gaps are carried
  to a year. On the demo data what is "worth raising" went from $1,829.14 to $71.71.
- The customer platform lives at `/portal` with its own sign-in, session and look, and nothing of
  the builder's. Customers → "Open customer platform" opens it in a new tab; the builder stays
  signed in. A person joins there with an invitation code.
- Its dashboard is purchasing analytics (`GET /portal/analytics`): what came in by day, location,
  supplier and item, and prices that moved. Each agent has a page with tabs.

Checks: Ruff; 455 SQLite tests passed (6 PG-only skips); strict TypeScript; 3 Vitest. New pages
walked in a browser with no failed requests. Not run: the browser suite, PostgreSQL suite.

## The demo made ready to show on a call

- `demo/restaurant/start.sh` starts the app on the live model (`live.env` laid over `.env` by
  `scripts/dev.sh`'s new `ENV_OVERLAY`). `demo/restaurant/reset.sh` returns Steel City Diners to
  its starting state in the local database without reading a page again, and keeps the login.
- Three invoices are kept out of the workspace to upload live (`customer.HELD_BACK`). Read cold,
  each came out right against the key on every field and line: 16 s, 22 s and 23 s; $0.0065.
- `apps/web/tests/demo/rehearse.mjs` walks the seven steps of `demo/restaurant/CALL.md` in a
  browser. Run twice in a row with a reset between: no response of 400 or above, no page error.
- Found while looking at every page: an invoice a statement lists that is not on file was counted
  as money found, so the three kept-back invoices showed as $912.85 "never received". It is now
  reported as not on file, with its amount, and is no longer in the money figure. Price gaps are
  grouped into findings (3, not 13 lines). The yearly figure and an unverified sentence about
  Xero drafts are gone. Page scans enlarge on a click; the line a check points at is marked; a
  read in progress says so.
- The held invoice in the demo is a real misreading (one case at $71.40 read as four at $17.85)
  that the price check caught.
- The invoice browser journey, its seed and the separate `.next-e2e` build directory, written
  outside this work, pass and are now in the repository.

Checks: `bash scripts/test.sh` (Ruff, 455 SQLite tests with 6 PG-only skips, TypeScript, Vitest,
8 browser journeys). Not run: PostgreSQL suite. Not verified: export files in a live Xero or
QuickBooks account, a real mailbox.

## Operations areas, shown on sample data

- New: `portal_records` (migration 0016) and `factory/operations.py`: nine operations areas and an
  overview, each worked out in code from recorded facts, with rules for what needs somebody.
- `demo/operations/` generates an invented four-location restaurant group over eight weeks (2,229
  records) and opens it as a customer workspace. Every page carries a "Sample data" mark.
- What this is not: no agent fills these areas, and no figure in that workspace is a real
  business's. Only supplier invoices and statements run on real documents.

Checks: Ruff; 458 SQLite tests passed (6 PG-only skips); strict TypeScript. All ten pages walked in
a browser at 1440 and 1280 wide with no refused request or page error. Not run: PostgreSQL suite,
migration 0016 on PostgreSQL.

## An agent for each operations area

- `factory/recording.py`: an operations agent's answer is checked and written into `portal_records`
  (migration 0017 adds `document_id`). Kinds are told from the answer's shape.
- Seven agents built through Agent Factory on generated documents, 24 examples each (8 development,
  6 selection, 10 held back), target 0.7, on gpt-6-luna: till reports, cash-up sheets, delivery
  payout statements, timesheets, stock counts, catering enquiries, certificates. Each scored 1.0 on
  its 10 held-back examples, for $0.008 to $0.021 a build. Installed in the sample workspace; 80 of
  its 81 starting documents were read exactly as the answers have them (one certificate's holder
  was misread and no check can catch it), and all 14 documents kept for live upload, in 2 to 6
  seconds each.
- Those scores are on clean typed PDFs from the same generator the agents were built on. They show
  the pipeline works, not how the agents would do on real documents.
- Found on the way: a derived answer schema made a repeated date a fixed vocabulary, so three
  agents rejected a week not among their examples and one recorded a statement under the wrong
  week. Dates are no longer a vocabulary (`intake.derive_schemas`); the three were rebuilt.
- Found on the way: with a location's stock count or timesheet for a week not yet in, its food cost
  and labour were divided by sales that included that week. Each is now set against the sales its
  paperwork covers, and missing paperwork is reported.
- The mock-up agents of the previous entry are gone. `demo/operations/build.sh` builds everything
  from nothing, `reset.sh` restores the starting state, `CALL.md` is the script.

Checks: `bash scripts/test.sh`; `rehearse-operations.mjs` twice in a row with a reset between, and
`rehearse.mjs` for the invoice demo: no response of 400 or above, no page error. Not run:
PostgreSQL suite, migrations 0016 and 0017 on PostgreSQL. Purchasing has no agent in the sample
workspace.

## Ready to leave the laptop, as far as that can be proven without accounts

**Hosting: proven locally, not deployed.**
- The whole suite passes on PostgreSQL: 473 passed. (The first run was cut short when the disk
  filled and PostgreSQL went into recovery; rerun clean.)
- `scripts/prod-local.sh up` builds the images and runs them in production mode beside the
  development app; `check` passed: health, demo sign-in off, a stranger refused, the owner
  registered and signed in, a customer workspace opened in PostgreSQL, migrations at 0017, a
  `pg_dump` backup, the web app built against the API, the worker running, and cross-origin
  requests allowed from the web address only.
- New for hosting: `REGISTRATION=invited` (required in production, with `OWNER_EMAILS`), because an
  open sign-up on a hosted instance lets a stranger spend the owner's model key; a provider's bare
  `postgresql://` address is accepted; the request-limit store can be given as host and port; the
  sign-in page hides the demo button and says accounts are by invitation.
- `render.yaml` and docs/DEPLOYMENT.md name Render, about $37 a month. Never submitted. The
  sandbox for builder-written code is not part of it.

**Mailbox: ready, blocked on credentials.**
- Outlook.com and Microsoft 365 take no password or app password for IMAP any more. The mailbox
  code could not have connected to one. Microsoft sign-in (XOAUTH2 with a stored refresh token) is
  added, with `scripts/outlook_signin.py` to get the token.
- The IMAP code had no tests of its own. It has five now, against a stand-in. Also fixed: the
  mailbox's position is read from the folder's opening; a message is found among other server
  updates; a refused sign-in says what to do; a logo in a signature is not taken for a document.
- `scripts/mailbox_check.py` connects a real mailbox, takes in one emailed invoice and proves no
  flag changed. Not run: no credentials.

**Accounting: specification-checked, not import-proven.**
- Against Intuit's pages: a QuickBooks file now stops before 1,000 rows as well as at 100 bills; a
  bill below zero stops the export; the heading is "Bill no."; dates are written as the customer
  sets. In the US only QuickBooks Online Advanced imports bills from a file.
- Against Xero's template as documented: an export is refused without a tax type, which was
  written blank. Xero's own help page could not be read here.

**Real documents: one more kind.**
- demo/sales: thirteen real point-of-sale sales summaries from In re Smokecraft Clarendon, LLC
  (Bankr. D. Md. 24-13609), three layouts, typed. Built through Agent Factory on five; **eight of
  eight held back right in all fourteen figures**, one round, $0.01. One restaurant, one system.
- Also searched for on RECAP: delivery platform payout statements, time cards, payroll registers,
  stock counts, cash-up sheets, licences. Hits exist, scattered one or two to a docket (time cards
  and liquor licences most often); no filing with a set large enough to build and measure on was
  found, and those were not gathered.

Checks: `bash scripts/test.sh`; both rehearsals; the PostgreSQL suite; `scripts/prod-local.sh check`.

## Simple local demo sign-in (2026-10-13)

- Both sign-in forms accept a username, so `demo` / `demo` opens the Harbor Table Group
  sample customer dashboard. Registration and joining still use email addresses.
- Operations seeding always sets this demo password, rather than generating one on a fresh
  setup, and refuses outside development. No authentication bypass was added.
- Verified the running app from both `/portal` and `/`: dashboard and Sample data mark
  visible, no failed HTTP requests (including 429) or page errors. Ruff, strict TypeScript,
  3 Vitest tests and 29 membership/portal API tests passed; 2 PostgreSQL-only tests skipped.
  Full browser and PostgreSQL suites were not rerun for this change.

## Customer sidebar follows the work (2026-10-13)

- Replaced installation-order navigation with groups: suppliers and stock, people and premises,
  sales and takings, finance, and customers. The Agents directory follows under Workspace.
- Installed supplier invoices appear first and statements under Finance, including workspaces
  that have operations areas. Empty groups disappear; unclassified areas/agents remain reachable.
- Verified strict TypeScript and 3 Vitest tests. Targeted browser checks in Harbor Table Group
  and Steel City Diners confirmed link order, navigation and active states, the Sample data mark,
  and retention of links at mobile width; zero failed HTTP responses, 429s or page errors.
  Inspected the desktop screenshot. Full browser and PostgreSQL suites were not rerun.

