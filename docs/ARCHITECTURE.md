# Architecture

The browser consumes a tenant-scoped FastAPI REST API and persisted SSE events.
PostgreSQL is the source of truth for users, memberships, agents, immutable versions,
build checkpoints, evaluations, executions, approvals, audit and usage. SQLite supports
isolated local tests. A database-leased worker advances one checkpoint per transaction;
completed iterations have unique keys so restart retries cannot duplicate results.

The factory designs configuration, never executable source. A separate runtime binds
only approved tools to an immutable version. Deterministic business calculations live
in tool implementations. Real execution uses OpenAI Agents SDK; local deterministic
execution is explicitly labeled. Evaluation forks fictional business state for each
case and compares outputs and side effects with independent expectations.

The optimizer receives development failures only. Regression and validation answers
remain outside optimizer context. Promotion compares measured outcomes and blocks
critical regressions. Deployment requires authorized review and pins a specific version.

Secrets are encrypted server-side. Tool access checks organization, connection status,
resource scope and read/write policy. Side effects create approval checkpoints by
default, with idempotency keys checked at the actual write boundary.

Live custom agents use a configured JSON Schema output adapter and SDK multi-tool
execution. Template preparation calls deterministic business policy tools. Version
configuration snapshots tool contracts and connection fingerprints, so rediscovery
cannot silently change a deployment. External writes persist dispatch intent before
I/O and require human reconciliation on ambiguous outcomes; fixture writes commit
atomically with their approval. Tenant business records are locked at approved writes
to protect inventory from concurrent updates. No external writes run in evaluations.

Official SDK reference consulted: https://developers.openai.com/api/docs/guides/agents/quickstart?lang=python
Installed openai-agents version 0.23.1 APIs were inspected locally.
