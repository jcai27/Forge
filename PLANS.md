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

Builder checks (2026-10-10): Ruff; 328 SQLite tests (6 PG-only skips); 334 PostgreSQL tests;
migration 0008 drift-free on both; 36 sandbox isolation checks; containerized worker-to-
sandbox end-to-end; strict TypeScript; 3 Vitest; all 6 browser journeys.
Live results on the OpenAI API with gpt-5.5 as builder, two builds per arm: the one-shot
optimizer and the harness both reach the target with held-out passing in 2 of 2 builds, the
harness at about ten times the builder spend. Research, a sandboxed model-written tool and an
inert connection draft each worked in directed exercises. The builder works with a real
model; the harness has not yet shown it is worth its cost.

Build inputs (2026-10-10, docs/INTAKE.md): datasets become split evaluation cases, context
documents reach the builder only, a build needs a source of truth, custom agents may have no
tools, and a build stopped at its limits reports a held-out score. Checks: Ruff; 366 SQLite
tests (6 PG-only skips); 372 PostgreSQL tests; migration 0009 drift-free and reversible on
both; strict TypeScript; 3 Vitest; all 7 browser journeys with zero HTTP 429s. One live build
from a task and a public data address ran end to end on OpenAI at 20 rows a side; it proves
the path, not quality. Next: the same build on the strongest model at 60 rows or more a side
(docs/PRODUCT.md P3), then the customer approver login (P7).

Real builds (2026-10-10, docs/RUNNING_BUILDS.md): a selection split the builder never reads
decides what is kept; provider failures are retried and never scored; live trials run in
parallel; replies are uncapped; usage is priced per model with input, cached and output
tokens; the final held-out pass is budgeted for; the example pool, confusion summary and
static check removal are available to the builder; hybrid mode; dataset removal. Checks:
Ruff; 396 SQLite tests (6 PG-only skips); 402 PostgreSQL tests; migrations 0009 to 0011
drift-free and reversible on both; strict TypeScript; 3 Vitest; 7 browser journeys with no
HTTP 429. Live on gpt-5.5 at 60 rows a side before the selection split: first version 85%
held out, builder's version 83%, so no measured improvement. Next: one clean gpt-5.5 run at
150/100/100 with the selection split and example pool (docs/PRODUCT.md P3).

Builder work still open, in priority order:

a. Harder benchmark task families, where a first proposal is often wrong, to learn whether
   investigation and screening pay for themselves. Include workflows over custom connectors
   and a mock vendor API with messy documentation, and more builds per arm.
b. Reject or flag `rules` keys that no tool reads, so a builder cannot add settings that do
   nothing.
c. Parallel trial execution, rerun-to-confirm promotion and a rotating held-out set.
d. Path parameters in the REST connector and non-REST proposals.
e. Reviewed third-party packages for generated tools; a hardened sandbox runtime for
   production (gVisor, Firecracker or managed).
f. The build timeline lags about two seconds behind a finished build before "Load more"
   appears. Tests now wait for it; consider refreshing the timeline when the build completes.
Do not use local models on this project; use the hosted key in `.env`.

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
