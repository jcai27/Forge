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
Worker termination during an unresolved provider request still needs a durable cost
reservation/reconciliation mechanism; process recovery of fixture evaluations and
deployment invocations is separately verified.

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
