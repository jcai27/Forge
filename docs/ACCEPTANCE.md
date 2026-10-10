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
| Generic connectors | REST/Postgres/file/webhook/email/MCP adapters and contract tests | Real PostgreSQL discovery/read/denied-write test passed; local MCP HTTP test remains; external credentials unavailable |
| Data discovery and least privilege | Integration test/discovery, typed registered tools, allowed tables/hosts, revocation | Resource-specific approval UX and contracts audit |
| Natural-language builder | Template inference, versioned baseline, live architect SDK role | Structured requirements and background architecture/usage verified; general reviewed Test Designer verified; broader arbitrary connector workflow journeys remain |
| Safe evaluation | Independent assertions, fresh fixture state, JSON schemas, dev/regression/validation splits | Replay/read-only grants, isolated state/schema/sequence checks and human review pass; rubric availability/budget tested, actual provider grades unavailable |
| Autonomous loop | Measured failed baseline → hypothesis → new version → retest → compare → promote; persisted per-case checkpoints | Real process kill/recovery passes for builds and invocations; repeated-trial variability implemented; Factory role crash reservations and lease/control boundaries are verified; evaluation/rubric/runtime model accounting remains |
| Regression protection | Critical stock bypass candidate rejected; competing stock approvals serialize correctly | Higher-score critical regression and equal aggregate regression hiding an individual failure are both rejected |
| Budgets and stopping | Iterations/cost/time/stagnation, cancel/pause/resume, pre-call runtime token reservation | Durable architecture/designer/optimizer reservations verified; evaluation/rubric/runtime durable provider accounting and broader resource audit remain |
| Trace/usage safety | Redacted secrets, external response trace summaries, audited actions | Mapped imports select declared fields and state evidence is summarized; broader raw output minimization and adversarial audit remain |
| Template A data/edge cases | 100 products, multiple customers, aliases, prices, inventory, history, 36 cases | Fractional cents and duplicate requests verified; broader parsing/unit policy checks remain |
| Templates B/C | Shared factory/runtime, independent suites, approved quote/hiring writes tested | Browser tests for both templates and scheduling constraints |
| Frontend pages/design | All required paths, actual controls, charts, workflow, responsive CSS; browser journey passed; screenshot inspected | Mobile and accessibility checks; list pagination; budget editing UX; in-progress immutable redirection browser flow now passes; human review browser flow passes |
| Deployment runtime | Approved version pinning, invocation/idempotency, approval completion, logs, pause and rollback | Schedules, signed webhooks, lifetime budgets and durable queue tested; production runtime audit remains |
| Production side effects | Default approval, permission recheck, dispatch intent, no automatic ambiguous retry | Administrator reconciliation receipts and concurrent stock/duplicate-request approvals verified; transport hardening remains |
| DX/documents | README, env sample, migrations, scripts, OpenAPI, engineering memory | Seed CLI/API examples beyond demo bootstrap and final runbook |
| Security governance | Encrypted secrets, JWT/membership/RBAC, audit, Redis rate limiter, approval boundaries, schema validation | Concurrent approvals/idempotency passed on PG; SSRF/DNS transport hardening and security/header audit remain |

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
