# Execution roadmap

Authoritative scope: docs/AGENT_FACTORY_SPEC.md. The complete goal remains active.
See docs/ACCEPTANCE.md for requirement-level evidence and gaps; chronological evidence
is in docs/PROGRESS.md. Latest verified milestone: 2026-10-09 corrected test-proposal browser review and
coalesced build-stream refreshes, verified without API rate-limit failures.

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

Latest checks: Ruff; 159 SQLite tests passed (4 PG-only skips); 163 PG tests passed;
strict TypeScript; 2 Vitest tests; three browser journeys; Alembic drift checks on both
DBs; populated migration upgrade/downgrade; optimized images and Compose health.
Latest scoped verification: 13 factory-role tests on each SQLite/PostgreSQL, Ruff,
TypeScript, 2 Vitest tests and all 3 browser journeys. The complete backend counts above
are from the unchanged runtime at the preceding milestone. These prove working slices,
not complete phases or the whole product specification.

Next work, in priority order:

1. Broader custom-workflow evidence across reusable connectors. Generated proposal
   correction/acceptance now passes a real browser journey with actual SDK-generated
   local fixtures, denied live grants, real isolated evaluation and persisted review.
   Verify arbitrary connector workflows and keep hidden answers outside optimizer context.
2. Broaden multi-turn deployment connector contracts, residual-budget rejection and
   concurrent policy/authorization audits. All public production invocation routes enter
   the durable deployment queue; direct execute is an internal helper with no standalone
   endpoint. Do not add an unprotected public execution path. Architecture/designer/
   optimizer/evaluation/rubric/deployment accounting is durable; actual provider billing
   reconciliation remains unavailable and unknown charges stay reserved.
3. Broader private-field minimization and email/Postgres transport bounds,
   safe deployment users/settings and tenant/relational enforcement audit.
4. Membership/invitation management, collection pagination, mobile/accessibility checks,
   template browser journeys and controlled manual editing/redirect usability.
5. Seed/API runbook and full requirement-by-requirement audit. Actual local TLS MCP
   initialization/discovery/call now passes; external provider credentials remain absent.

External dependencies: no OPENAI_API_KEY or real provider credentials/app registrations
are configured. Actual OpenAI model/rubric responses and external integrations remain
unverified. Continue local functionality and contract verification independently.
No unauthorized production writes have occurred or are authorized by this roadmap.
