# Builder roles and quality policy

Agent creation persists a valid baseline configuration and structured business
requirements immediately. Live model-backed design runs in the durable worker's
DESIGNING stage, so the browser need not remain open. The combined Requirements
Analyst/Agent Architect uses only supplied registered capabilities and returns a typed
AgentSpec. Business requirements include objective, inputs/outputs, systems, steps,
rules, exceptions, success metrics, side-effect policy and explicit assumptions.

The deterministic templates use authored domain defaults, not a claimed live model.
When a live workflow has no authored cases, a general SDK Test Designer proposes
independent scenarios with development/regression/held-out splits. Proposals remain in
the build checkpoint until an administrator corrects and accepts them; they do not
count as executed evidence. The build page exposes this review form. In deterministic
mode, custom workflows still need authored cases. The optimizer receives only
development failure evidence, never regression or held-out answers.

Architecture and optimization calls use the real Agents SDK with structured output,
an output-token ceiling, timeout and pre-call conservative budget reservation. Token
and configured cost estimates are recorded as factory-role UsageRecords linked to
BuildJob. Measured usage survives a handled output/scope failure, and zero budget
prevents provider dispatch. The cost estimate is configurable, not a provider invoice.
Factory roles commit a `pending` UsageRecord and charge its `reserved_cost` to the
build before dispatch. A response settles that reservation to observed token usage and
its configured cost estimate (`recorded`). A failed/interrupted request becomes
`uncertain`; its reservation remains against the budget, without inventing tokens or
actual billing. Recovery marks abandoned pending requests uncertain and permits a
fresh attempt only within the remaining budget. Automatic HTTP retries are disabled
for these roles. The lease outlives the bounded request; returning workers recheck the
lease and user state before persisting results, preserving pause/cancel decisions.

Independent rubric grading now uses the same durable reservation principle with a
run-linked rubric_evaluator ledger entry and optional build ownership. Unknown charges
survive real process termination; observed grading usage is charged once, including
manual retries. Paused/cancelled/redirected builds and transferred leases survive a
returning grader. Live evaluated-agent calls now use evaluation_agent reservations,
observed settlement and model/tool control checks. Their isolated/read-only tools permit
durable checkpoints without committing production state. Killed executions become
failed/uncertain on recovery and fresh attempts remain budget-bound. Deployment calls
use separate production hooks; read-only evaluation hooks cannot execute them.

`GET /usage` exposes tenant-owned paginated ledger entries. Metrics report observed
cost estimates and outstanding reservations separately; build details expose
`factory_observed_cost` and `factory_reserved_cost`. The build page labels unresolved
reservations. Provider billing reconciliation is not yet available, so unknown charges
are conservatively retained. Queued live deployment calls now persist run-owned
`deployment_agent` reservations before each dispatch. Observed usage settles independently
of result validity; unknown charges survive worker termination and remain reserved against
the deployment lifetime budget after the queue allocation is released. Recovery includes
previous usage/reservations in the invocation ceiling. Hidden HTTP retries are disabled.

Deployment model/tool checkpoints recheck membership, approved pinned version, active
configuration and worker ownership. Connector and fixture approvals stay staged until
validated final output; the final result, approvals and queue allocation settlement commit
together. Returning stale workers retain reported usage but cannot publish their result.
A late response after successor completion converts the retained unknown reservation to
observed usage without duplicating approvals. Standalone production/preview calls outside
the deployment queue still need durable accounting and authorization checkpoints.

Each immutable AgentSpec carries a `quality_policy`:

```json
{
  "minimum_score": 0.95,
  "minimum_cases": 1,
  "minimum_validation_cases": 1,
  "maximum_mean_latency_ms": 60000,
  "maximum_evaluation_cost": 1000,
  "objective": "pass_rate",
  "minimum_improvement": 0
}
```

Administrators edit it by saving a new version in Studio. Separate development,
regression and held-out validation evidence, critical-case protection, approval/safety
checks and resolved reviews always remain mandatory. Models cannot change this user
policy, add capabilities, remove approval/isolation guards or expand resource ceilings.
Recorded design metrics are server-owned when a person edits a configuration.

The loop retains intermediate best-known candidates while improving toward the target.
Readiness uses the stricter of build target score and policy minimum score, with distinct
case-count, held-out, cost and latency gates. Trial repetition does not inflate the
distinct-case count. Deployment review applies the policy to current completed evidence.

Pass-rate objectives require measured score improvement. Cost/latency objectives require
a lower measured cost/latency while meeting the minimum quality score and preserving
aggregate task quality. `minimum_improvement` uses pass-rate fractions, dollars or
milliseconds for those objectives respectively. Every previously passing regression
trial must still pass; an equal aggregate regression rate cannot hide a new failure.
Critical or safety violations always block promotion.

Local SDK provider-contract tests verify role output parsing, scope enforcement,
recorded usage and budget behavior. They do not establish that a real provider produces
correct architectures or improvements. Actual provider execution remains unverified
until authorized credentials are configured.

Test proposals require six or more distinct cases, assertions, all three splits and a
critical regression scenario. Tool recordings must match authorized IDs and schemas.
Generated proposals cannot grant live access or imported-data visibility. Accept with
`POST /builds/{id}/test-proposals/accept` using the corrected `{rationale, cases}` plan.
This imports cases atomically, audits the reviewer and resumes the same build. Repeated
acceptance returns a conflict. Assertions then grade actual executions; accepting a
proposal never changes a scorecard or authorizes production side effects.


In-progress builds can be redirected through the build page or
`POST /builds/{id}/redirect` with `{expected_version_id, reason, spec}`. The expected
candidate guards against stale edits. The change creates a new immutable version,
invalidates the previous worker lease and starts fresh evaluation. Prior evaluations
and iterations remain in history; old scorecards/proposals are not reused for the new
objective. Spending, start time, iteration count and budget limits are retained, and
redirection is rejected once no evaluation iterations remain. Tenant/RBAC, approved
capability scope, mandatory guards and administrator-only policy changes still apply.
Review authored scenario expectations after changing requirements. Redirection does
not modify a deployed version or authorize business writes.
