# Execution roadmap

Authoritative scope: docs/AGENT_FACTORY_SPEC.md. The complete goal remains active.
See docs/ACCEPTANCE.md for requirement-level evidence and gaps; chronological evidence
is in docs/PROGRESS.md. Latest verified milestone: 2026-10-09 durable factory provider reservations.

Verified working slices:

1. Monorepo, FastAPI/Next.js/worker, relational schema, Alembic and full Compose startup.
2. Immutable structured specs, real SDK tool dispatch, explicit deterministic demo mode.
3. Fixture/REST/Postgres/file/webhook/email/MCP connectors and permission boundaries.
4. Natural-language baseline, structured requirements, background live architecture.
5. Isolated output/state/schema/sequence evaluation, replay/read-only grants, mapped
   imports, trial variability, rubric availability/budget behavior and human review.
6. Persistent evaluate/diagnose/revise/retest/compare loop with critical and individual
   regression protection, separate held-out validation, pause/resume/cancel and budgets.
7. All required UI routes, persisted SSE progress, studio, lab, comparisons and approvals.
8. Pinned deployment, durable invocation queue, signed webhooks/schedules, lifetime
   limits, rollback, approved writes and explicit uncertain-write reconciliation.
9. Orders/quotes/administrative hiring share runtime, factory, tools and assertions.
10. Real worker kill/recovery, tenant/RBAC/secret tests and PG concurrency tests.

Latest checks: Ruff; 56 SQLite tests passed (4 PG-only skips); 60 PG tests passed;
strict TypeScript; 2 Vitest tests; complete browser flow; Alembic drift checks on both
DBs; populated migration upgrade/downgrade; optimized images and Compose health.
These prove working slices, not complete phases or the whole product specification.

Next work, in priority order:

1. Broader custom-workflow evidence and build redirection. Background Test Designer
   proposals now require administrator correction/acceptance; verify more connector
   workflows and keep hidden answers outside optimizer context.
2. Extend durable provider reservations to evaluation/rubric/deployment model calls
   while preserving transactional tool/approval safety. Architecture/designer/optimizer
   now retain unknown charges across real process termination, disable hidden HTTP
   retries and preserve pause/cancel/lease ownership. Billing reconciliation remains
   unavailable; unknown charges are conservatively retained. Verify broader contracts
   without inventing metrics.
3. Known-secret-value minimization, streaming response bounds, DNS/SSRF transport audit,
   safe deployment users/settings and tenant/relational enforcement audit.
4. Membership/invitation management, collection pagination, mobile/accessibility checks,
   template browser journeys and controlled manual editing/redirect usability.
5. Seed/API runbook, local MCP transport test and full requirement-by-requirement audit.

External dependencies: no OPENAI_API_KEY or real provider credentials/app registrations
are configured. Actual OpenAI model/rubric responses and external integrations remain
unverified. Continue local functionality and contract verification independently.
No unauthorized production writes have occurred or are authorized by this roadmap.
