# Acceptance evidence and remaining audit

This is a working implementation with verified vertical slices, not a declaration
that the complete product specification is finished. Authoritative scope remains
AGENT_FACTORY_SPEC.md. The goal stays active until remaining feasible work is done.

| Specification requirement | Current evidence | Remaining verification/work |
| --- | --- | --- |
| Monorepo/default stack | FastAPI, SQLAlchemy, Alembic, SDK, Next App Router, TS, Tailwind, shadcn-style primitives, TanStack, React Flow, Recharts, Redis, Compose | API/worker/web/PG/Redis Compose startup verified; production runbook audit remains |
| All 25 required relational entities | Frozen migration with FK/index/unique constraints; PG/SQLite migration checks | Composite tenant FK/DB enforcement audit |
| Auth and organization/RBAC boundaries | Authenticated APIs, membership checks, tenant negative tests, editor/admin roles | Membership invitation/add flow; pagination audit |
| Immutable structured specs/runtime | Version creation/edit API, pinned tool contracts, SDK reconstruction | Live provider calls unavailable without key; multi-tool custom SDK provider-contract test passes; actual provider responses unavailable |
| Generic connectors | REST/Postgres/file/webhook/email/MCP adapters and contract tests; actual local TLS MCP SDK initialization/discovery/call with bounded JSON/SSE, compression, pagination and deadline tests | Real PostgreSQL discovery/read/denied-write test passed; email/Postgres transport bounds and external credentials remain |
| Data discovery and least privilege | Integration test/discovery, typed registered tools, allowed tables/hosts, revocation | Resource-specific approval UX and contracts audit |
| Natural-language builder | Template inference, versioned baseline, live architect SDK role | Structured requirements and background architecture/usage verified; general reviewed Test Designer verified; broader arbitrary connector workflow journeys remain |
| Safe evaluation | Independent assertions, fresh fixture state, JSON schemas, dev/regression/validation splits | Replay/read-only grants, isolated state/schema/sequence checks and human review pass; rubric availability/budget tested, actual provider grades unavailable |
| Autonomous loop | Measured failed baseline → hypothesis → new version → retest → compare → promote; persisted per-case checkpoints | Real process kill/recovery passes for builds and invocations; repeated-trial variability implemented; factory/evaluation/rubric reservations and control boundaries verified; queued deployment ledger/recovery verified; standalone production accounting remains |
| Regression protection | Critical stock bypass candidate rejected; competing stock approvals serialize correctly | Higher-score critical regression and equal aggregate regression hiding an individual failure are both rejected |
| Budgets and stopping | Iterations/cost/time/stagnation, cancel/pause/resume, pre-call runtime token reservation; durable evaluation/rubric reservations and settlement | Durable architecture/designer/optimizer/evaluation/rubric reservations verified; queued deployment reservations/settlement verified; standalone production accounting and broader resource audit remain |
| Trace/usage safety | Redacted secrets, external response trace summaries, audited actions | Mapped imports select declared fields and state evidence is summarized; broader raw output minimization and adversarial audit remain |
| Template A data/edge cases | 100 products, multiple customers, aliases, prices, inventory, history, 36 cases | Fractional cents and duplicate requests verified; broader parsing/unit policy checks remain |
| Templates B/C | Shared factory/runtime, independent suites, approved quote/hiring writes tested | Browser tests for both templates and scheduling constraints |
| Frontend pages/design | All required paths, actual controls, charts, workflow, responsive CSS; browser journey passed; screenshot inspected | Mobile and accessibility checks; list pagination; budget editing UX; in-progress immutable redirection browser flow now passes; human review browser flow passes |
| Deployment runtime | Approved version pinning, invocation/idempotency, approval completion, logs, pause and rollback | Schedules, signed webhooks, lifetime budgets and durable queue tested; production runtime audit remains |
| Production side effects | Default approval, permission recheck, dispatch intent, no automatic ambiguous retry | Administrator reconciliation receipts and concurrent stock/duplicate-request approvals verified; transport hardening remains |
| DX/documents | README, env sample, migrations, scripts, OpenAPI, engineering memory | Seed CLI/API examples beyond demo bootstrap and final runbook |
| Security governance | Encrypted secrets, JWT/membership/RBAC, audit, Redis rate limiter, approval boundaries, schema validation; REST/MCP connection-time public-IP pinning and verified TLS identity | Concurrent approvals/idempotency passed on PG; other connector transport bounds and full security/header audit remain |

Numbered tests 1–7 and 9 have backend behavioral coverage. Test 8 has real process kill/restart
coverage for builds and invocations. Test 10 has a passing full browser
flow through project creation, improvement evidence, review/deployment and approvals.
Scores are calculated from assertions, not overwritten. Demo runs are explicitly
labeled and exercise real SDK tools without a live model. No production writes were
performed. OAuth registrations, live OpenAI provider calls and external system
credentials are not available in this environment; local/mock contracts remain testable.

2026-10-09: configured quality thresholds/objectives are persisted in immutable specs;
case-count/latency approval gates and administrator policy edits are tested. Models
cannot change quality policy or expand resource ceilings. Current checks: 45 SQLite
(4 PG-only skips), 49 PostgreSQL, TypeScript/Vitest/Playwright and Compose builds pass.


2026-10-09: factory architecture/designer/optimizer pending reservations now survive
real process kills, conservatively retain unknown charges and prevent budget-bypassing
retries. HTTP failure dispatches once; pause/cancel decisions survive returning requests.
Usage API/metrics distinguish observed estimates and reservations with tenant filters.
Final checks: 56 SQLite tests (4 PG-only skips), 60 PostgreSQL tests, TypeScript,
Vitest/Playwright, migrations and rebuilt Compose services pass. Equivalent durable
accounting for evaluation/rubric/deployment model calls remains incomplete.


2026-10-09: in-progress redirection creates an immutable candidate and reruns actual
independent/held-out evaluation, retains global budgets/history and rejects stale,
unauthorized or exhausted-budget requests. Returning SDK role responses cannot overwrite
the redirected checkpoint. Both browser journeys now wait on actual build status;
a static stage label is not readiness evidence. Auth profile reads no longer exhaust
credential quotas, and rate protection errors preserve CORS/security headers.
Final checks: 60 SQLite tests (4 PG-only skips), 64 PostgreSQL tests, strict TypeScript,
2 Vitest tests, 2 complete browser journeys, migrations and rebuilt Compose pass.


2026-10-09: known tenant/global credential values and conventional encodings are filtered
at model/tool/output/trace/browser boundaries. Revoked ciphertext is redaction-only,
with active dispatch credentials removed; historical filtering and tenant separation
are tested. This does not prove complete PII/minimization or encoding coverage.
Final checks: 64 SQLite tests (4 PG-only skips), 68 PostgreSQL tests, TypeScript,
Vitest, both browser journeys, migrations and rebuilt Compose services pass.


2026-10-09: REST responses have verified streaming wire/decoded bounds, bounded
compression, body closure and HTTP-phase deadlines. Read-only 429 retries are bounded;
write methods dispatch once. DNS rebinding/pinning and other connector transport paths
remain unverified/incomplete. Final checks: 74 SQLite tests (4 PG-only skips), 78 PG
tests, Ruff/TypeScript/Vitest, both browser journeys, migration drift and rebuilt Compose.


2026-10-09: REST/MCP new connections resolve within the deadline, validate every DNS
answer and connect to a numeric public IP with the original verified TLS/HTTP hostname.
Private/metadata/transition/scoped answers and mixed public/private DNS reject before
socket dispatch. Exact-origin, proxy, DNS-cancellation and native body-error boundaries
pass. Actual installed MCP SDK initialization/discovery/call passes through an owned
local TLS fixture; wrong-host certificates reject before HTTP dispatch. External live
credentials and MCP stream/result-size bounds remain unavailable/incomplete respectively.
Final checks: 92 SQLite tests (4 PG-only skips), 96 PostgreSQL tests, Ruff/TypeScript,
2 Vitest tests, both browser journeys, migration drift and rebuilt Compose services pass.


2026-10-09: MCP responses have shared 2 MB wire/decoded session budgets before JSON/SSE
parsing, bounded gzip/deflate, failed-stream closure, 10-page discovery and 15-second
operation/session deadlines. Expired sessions reject later dispatch including cleanup;
exhausted decoded budgets cannot enable unlimited zlib output on another stream. Actual
SDK/TLS tests pass valid compressed JSON/SSE, reject a gzip bomb without another tool
call, cancel a trickle and reject pagination at 10 pages. Email/Postgres transport and
the wider security/runtime audit remain incomplete. Full checks: 112 SQLite tests
(4 PG-only skips), 116 PostgreSQL tests, Ruff/TypeScript/Vitest and both browser journeys,
migration drift and rebuilt Compose pass. The final iterator scope adjustment also
passes all 23 focused MCP tests and is present in rebuilt API/worker images.


2026-10-09: read-only rubric grading commits reservations before SDK dispatch and
retains unknown charges across a real process kill. Observed settlement, worker control/
lease/redirection, once-only checkpoint/manual-retry charging, and interleaved-result
publication pass on SQLite and PostgreSQL. Deterministic failures remain failed;
unknown charges remain separate and cannot establish cost savings. Main evaluated-agent
and deployment model calls still need equivalent durable transaction/accounting work.
Final checks: 128 SQLite tests (4 PG-only skips), 132 PostgreSQL tests, Ruff/TypeScript,
Vitest, both browser journeys, migration drift and rebuilt Compose health pass. Actual
OpenAI grading remains unverified without credentials; fixtures exercise SDK contracts.


2026-10-09: live evaluated-agent calls now use durable run/build reservations and observed
settlement with provider HTTP retries disabled. Real process interruption retains unknown
charges and recovery marks orphaned execution failed. Model/tool boundary controls block
further dispatch after pause/cancel/lease transfer; worker checkpoints charge settled
usage once. Standalone evaluations are run-owned, and production execution cannot use
these accounting hooks. Real SDK fixture tools execute without production mutations or
approvals. Deployment/production durable accounting and wider acceptance remain incomplete.
Final checks: 139 SQLite tests (4 PG-only skips), 143 PostgreSQL tests, Ruff/TypeScript,
Vitest, both browser journeys, migration drift and rebuilt Compose health pass. Actual
OpenAI/provider responses remain unverified without credentials.


2026-10-09: production connector write requests remain staged until valid final output.
Real SDK tests commit an interim checkpoint and inspect a second session: invalid output,
provider failure and timeout publish no approval, while a valid result publishes a
pending request and only explicit approval invokes the fictional adapter. Queued/running/
failed runs cannot dispatch, and stale requests can be rejected safely. Durable deployment
accounting remains incomplete; staging establishes its approval transaction prerequisite.
Final checks: 149 SQLite tests (4 PG-only skips), 153 PostgreSQL tests, Ruff/TypeScript,
Vitest, both browser journeys, migration drift and rebuilt Compose health pass.


2026-10-09: queued deployment calls now persist per-model reservations before dispatch,
retain unknown charges through real process termination/recovery, settle observed usage
once and disable hidden HTTP retries. Authorization/lease checks stop returning revoked
workers before tool dispatch. Final results/approvals commit with queue settlement;
late responses after successor completion retain usage without republishing approvals.
Pause, membership revocation, version unapproval, budget reduction, lease transfer,
provider errors and actual HTTP failure contracts pass. These are local SDK fixtures,
not live provider responses. Standalone production/preview accounting, broader multi-turn
connector/concurrent-policy coverage and the remaining full acceptance audit are open.
Final checks: 159 SQLite tests (4 PG-only skips), 163 PostgreSQL tests, Ruff/TypeScript,
2 Vitest tests, both browser journeys, both migration drift checks and rebuilt Compose
startup/API health/dashboard HTTP checks pass.
