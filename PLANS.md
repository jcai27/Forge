# Execution roadmap

Authoritative scope: docs/AGENT_FACTORY_SPEC.md. The complete goal remains active.
See docs/ACCEPTANCE.md for requirement-level evidence and gaps; chronological evidence
is in docs/PROGRESS.md. Latest verified milestone: 2026-10-09 builder accounting/quality.

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

Latest checks: Ruff; 45 SQLite tests passed (4 PG-only skips); 49 PG tests passed;
strict TypeScript; 2 Vitest tests; complete browser flow; Alembic drift checks on both
DBs; populated migration upgrade/downgrade; optimized images and Compose health.
These prove working slices, not complete phases or the whole product specification.

Next work, in priority order:

1. General background Test Designer with reviewed proposals, custom-workflow evidence
   and redirecting builds. Avoid self-confirming generated answers or hidden-answer leaks.
2. Durable provider-call cost reservation/recovery for process termination mid-request.
   Handled architecture/optimizer failures retain measured usage; abrupt crashes remain
   an accounting gap. Verify SDK role contracts more broadly without inventing metrics.
3. Known-secret-value minimization, streaming response bounds, DNS/SSRF transport audit,
   safe deployment users/settings and tenant/relational enforcement audit.
4. Membership/invitation management, collection pagination, mobile/accessibility checks,
   template browser journeys and controlled manual editing/redirect usability.
5. Seed/API runbook, local MCP transport test and full requirement-by-requirement audit.

External dependencies: no OPENAI_API_KEY or real provider credentials/app registrations
are configured. Actual OpenAI model/rubric responses and external integrations remain
unverified. Continue local functionality and contract verification independently.
No unauthorized production writes have occurred or are authorized by this roadmap.
