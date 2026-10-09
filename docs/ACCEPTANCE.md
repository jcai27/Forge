# Acceptance evidence and remaining audit

This is a working implementation with verified vertical slices, not a declaration
that the complete product specification is finished. Authoritative scope remains
AGENT_FACTORY_SPEC.md. The goal stays active until remaining feasible work is done.

| Specification requirement | Current evidence | Remaining verification/work |
| --- | --- | --- |
| Monorepo/default stack | FastAPI, SQLAlchemy, Alembic, SDK, Next App Router, TS, Tailwind, shadcn-style primitives, TanStack, React Flow, Recharts, Redis, Compose | Full Compose startup verification in progress |
| All 25 required relational entities | Frozen migration with FK/index/unique constraints; PG/SQLite migration checks | Composite tenant FK/DB enforcement audit |
| Auth and organization/RBAC boundaries | Authenticated APIs, membership checks, tenant negative tests, editor/admin roles | Membership invitation/add flow; pagination audit |
| Immutable structured specs/runtime | Version creation/edit API, pinned tool contracts, SDK reconstruction | Live provider calls unavailable without key; complete multi-tool custom SDK contract test |
| Generic connectors | REST/Postgres/file/webhook/email/MCP adapters and contract tests | Real Postgres tool execution test; local MCP HTTP test; external credentials unavailable |
| Data discovery and least privilege | Integration test/discovery, typed registered tools, allowed tables/hosts, revocation | Resource-specific approval UX and contracts audit |
| Natural-language builder | Template inference, versioned baseline, live architect SDK role | Persist structured requirements; background design stage, arbitrary business workflow tests |
| Safe evaluation | Independent assertions, fresh fixture state, JSON schemas, dev/regression/validation splits | Replay adapters and authorized read-only checks; DB-state and sequence assertions; qualitative rubrics and human review |
| Autonomous loop | Measured failed baseline → hypothesis → new version → retest → compare → promote; persisted per-case checkpoints | End-to-end worker process kill/recovery; repeated-trial variability and complete resource budget accounting |
| Regression protection | Critical stock bypass candidate rejected | Candidate that improves development yet breaks critical regression explicit test |
| Budgets and stopping | Iterations/cost/time/stagnation, cancel/pause/resume, pre-call runtime token reservation | Builder/optimizer cost accounting, concurrency/race recovery tests |
| Trace/usage safety | Redacted secrets, external response trace summaries, audited actions | Raw input/output private-data minimization and secret leak adversarial tests |
| Template A data/edge cases | 100 products, multiple customers, aliases, prices, inventory, history, 36 cases | Fractional quantities/unit policies and broader real parsing checks |
| Templates B/C | Shared factory/runtime, independent suites, approved quote/hiring writes tested | Browser tests for both templates and scheduling constraints |
| Frontend pages/design | All required paths, actual controls, charts, workflow, responsive CSS; browser journey passed; screenshot inspected | Mobile and accessibility checks; list pagination; budget and redirect editing UX |
| Deployment runtime | Approved version pinning, invocation/idempotency, approval completion, logs, pause and rollback | Scheduled invocation, signed invocation webhooks, per-deployment lifetime budgets |
| Production side effects | Default approval, permission recheck, dispatch intent, no automatic ambiguous retry | Explicit reconciliation action/receipts and concurrency proof |
| DX/documents | README, env sample, migrations, scripts, OpenAPI, engineering memory | Seed CLI/API examples beyond demo bootstrap and final runbook |
| Security governance | Encrypted secrets, JWT/membership/RBAC, audit, Redis rate limiter, approval boundaries, schema validation | Concurrency tests, SSRF/DNS transport hardening, security/header audit |

Numbered tests 1–7 and 9 have backend behavioral coverage. Test 8 has session restart
coverage, with process crash verification pending. Test 10 has a passing full browser
flow through project creation, improvement evidence, review/deployment and approvals.
Scores are calculated from assertions, not overwritten. Demo runs are explicitly
labeled and exercise real SDK tools without a live model. No production writes were
performed. OAuth registrations, live OpenAI provider calls and external system
credentials are not available in this environment; local/mock contracts remain testable.
