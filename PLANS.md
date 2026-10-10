# Execution roadmap

Authoritative scope: docs/AGENT_FACTORY_SPEC.md. The complete goal remains active.
See docs/ACCEPTANCE.md for requirement-level evidence and gaps; chronological evidence
is in docs/PROGRESS.md. Latest verified milestone: 2026-10-10 builder harness (docs/BUILDER.md):
search-loop fixes, tool-using optimizer with typed patches, screened multi-candidate rounds,
executed bundle fields, isolated open-web research, sandboxed builder-written tools,
connection proposals, shadow comparison, release dossier and cases from real runs.

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

Latest checks: Ruff; 170 SQLite tests passed (6 PG-only skips); all 176 PG tests passed;
strict TypeScript; 3 Vitest tests; five browser journeys with zero HTTP 429s; Alembic
upgrade/drift checks on both DBs; populated migration upgrade/downgrade; optimized images
and Compose startup/health. These prove working slices, not complete phases or the
whole product specification.

Builder checks (2026-10-10): Ruff; 326 SQLite tests (6 PG-only skips); 332 PostgreSQL tests;
migration 0008 drift-free on both; 36 sandbox isolation checks; containerized worker-to-
sandbox end-to-end; strict TypeScript; 3 Vitest; production web build; all 6 browser journeys.
Search benchmark with a simulated proposer, 30 builds per arm: history raises target-reached
from 67% to 100% and cuts trials by about a quarter; screening cuts full evaluations by 30%.
Real-model runs used a local llama3.2:3b, the only model available, and exposed eleven
defects, now fixed. With the builder isolated, eight builds per arm: the harness improved
the agent in 6 of 8 builds (2 reached the target with held-out passing) and the one-shot
optimizer in 0 of 8. Caveats: one weak model, one task family, unequal builder spend.
Research and a generated tool were each driven by the real model a few times; a connection
draft never was.

Builder work still open, in priority order:

a. Repeat the live benchmark with a capable model and equal builder spend per arm
   (`python -m benchmarks.search --live`). It needs an API key or a larger local model through
   `OPENAI_BASE_URL`. Add workflows over custom connectors and a mock vendor API with messy
   documentation, and get a connection draft out of a real model.
b. Parallel trial execution, rerun-to-confirm promotion and a rotating held-out set.
c. Path parameters in the REST connector and non-REST proposals.
d. Reviewed third-party packages for generated tools; a hardened sandbox runtime for
   production (gVisor, Firecracker or managed).
e. The build timeline lags about two seconds behind a finished build before "Load more"
   appears. Tests now wait for it; consider refreshing the timeline when the build completes.

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
4. Secondary audit/trace/trigger/invocation collection pagination and suite selection UX,
   mobile/accessibility checks,
   template browser journeys and controlled manual editing/redirect usability.
5. Seed/API runbook and full requirement-by-requirement audit. Actual local TLS MCP
   initialization/discovery/call now passes; external provider credentials remain absent.

External dependencies: no OPENAI_API_KEY or real provider credentials/app registrations
are configured. Actual OpenAI model/rubric responses and external integrations remain
unverified. Continue local functionality and contract verification independently.
No unauthorized production writes have occurred or are authorized by this roadmap.
