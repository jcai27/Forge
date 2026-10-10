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
