# Architecture

The browser consumes a tenant-scoped FastAPI REST API and persisted SSE events.
PostgreSQL is the source of truth for users, memberships, agents, immutable versions,
build checkpoints, evaluations, executions, approvals, audit and usage. SQLite supports
isolated local tests. A database-leased worker advances one checkpoint per transaction;
completed iterations have unique keys so restart retries cannot duplicate results.

The factory designs configuration, and may also write small tools as code. Builder-written
code never runs in the API or worker: it runs in a separate sandbox service with no network,
credentials or host disk, reaches systems only through capability calls the worker performs
on its behalf, and is pinned by hash in the immutable version (see BUILDER.md). A separate
runtime binds only approved tools to an immutable version. Deterministic business calculations live
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

Manual, scheduled and signed webhook invocations enqueue a RuntimeJob with a pinned
version and cost reservation. Queue claims have expiring database leases; execution
and completion commit atomically. Schedules coalesce missed intervals after downtime.
Workers recheck creator membership and deployment state before every invocation.
Approval writes serialize on the tenant before reading state, including newly inserted
orders. Uncertain external dispatch can be reconciled by an administrator with a
provider receipt; reconciliation records an outcome and never performs another send.

EvaluationCase environments separate fictional forks, ordered connector replay and
explicitly authorized read-only checks. Replay verifies exact tool arguments and never
constructs a live adapter. Imported resources require administrator authorization,
model visibility and field mapping; only selected columns enter the isolated fork.
Grading uses independent deterministic output/state/schema/sequence assertions and
optional rubric or human evidence. Pending reviews halt promotion and build progress;
resumption retains completed trials. Model grading records usage under remaining budgets.

Creation persists a structured baseline; live requirements/architecture execute in the
worker. Factory-role usage shares the usage ledger with runtime and grading records,
with a separate job link. User quality policies and resource ceilings stay outside model
control. Promotion checks previously passing regression trials individually, then the
configured objective; readiness and review enforce held-out, case-count, cost and latency
thresholds. See FACTORY.md for defaults, accounting limits and remaining Test Designer work.

Official SDK reference consulted: https://developers.openai.com/api/docs/guides/agents/quickstart?lang=python
Installed openai-agents version 0.23.1 APIs were inspected locally.
