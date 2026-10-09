# Execution roadmap

Authoritative specification: docs/AGENT_FACTORY_SPEC.md.

1. Foundation: monorepo, settings, relational schema, migrations, API, worker, compose.
2. Runtime: immutable specs, registered tools, real SDK and explicit deterministic mode.
3. Integrations: approved typed tools, fixture ERP, REST/Postgres/files/webhook/email/MCP.
4. Builder: structured requirements and architecture from natural language.
5. Evaluation: independent assertions, reset state, split suites, traces and scorecards.
6. Improvement: durable checkpoints, diagnostic hypotheses, candidates, regression gates.
7. Frontend: all specified pages, live persisted event progress and functional controls.
8. Deployment: approval, pinning, invocation, resumption, rollback, monitoring.
9. Templates: orders, quotes, hiring on shared tooling and runtime.
10. Hardening: acceptance tests 1–10, recovery, tenant isolation, documentation.

Current: foundation and complete demo vertical slice verified. Continue the remaining
requirements in docs/ACCEPTANCE.md; the full product goal is still active.
Dependencies: package installation; PostgreSQL/Redis via Docker; optional OpenAI key.
Known limitations: repository initially contained only the specification at root.

Verified backend progress: runtime/tool execution, fictional integration, versioned
builder, independent evaluations, checkpointed improvement, approval and deployment
APIs. Ten backend tests pass. Phase 1 remains open until frontend/local startup is
verified; phases 2–6 have a working demo vertical slice, with live/connector hardening
still required. Next: full frontend and browser E2E, PostgreSQL migration checks,
connector contracts, rate/budget/retry security, deployment schedules/webhooks.

2026-10-09 verified milestone: durable deployment invocation queue, signed invocation
webhooks, interval schedules, lifetime cost/invocation budgets, explicit external-write
reconciliation, real process kill/recovery, PostgreSQL connector execution and concurrent
approval/idempotency checks. Latest checks: 29 SQLite tests (4 PG-only skips), 33
PostgreSQL tests, Ruff, strict TypeScript, 2 Vitest tests, browser flow, both Docker
images and complete Compose startup. Fractional cents and duplicate incoming requests
are checked at the actual approval boundary. No live credentials are configured.
Next: replay/read-only evaluation environments, expected test state and tool sequence
checks, qualitative and human review evidence, repeated-trial variability, builder roles
and accounting, then remaining governance/frontend/security audit. Full goal remains active.

Verified frontend milestone: all specified routes, live persisted build events, studio,
evaluation lab, comparisons, integration forms, approvals, deployments and execution
logs. Complete browser acceptance path passes. Current automated checks: Ruff clean,
20 backend tests, 2 Vitest tests, strict TypeScript, Playwright flow, optimized Next build.
PostgreSQL isolated-schema tests and migration drift checks pass. Docker API/web images
build. Remaining work is explicitly listed at the end of docs/PROGRESS.md; prioritize
scheduling/webhook deployment runtime, replay evaluation, comprehensive governance,
general live model integration tests, and durable process/concurrency recovery next.
