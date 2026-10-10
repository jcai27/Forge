# Evaluation environments and evidence

Every trial forks its test state. Fictional ERP changes remain in that fork and never
update live BusinessRecord rows. Development failures are the only case answers shared
with optimization; regression and validation evidence stay outside optimizer context.

Create cases with `POST /suites/{suite_id}/cases` or the Evaluation Lab JSON form.
Sources have distinct behavior:

- `synthetic`: authored fixture scenarios. External connector calls are forbidden.
- `replay`: exact ordered tool recordings. Tool IDs, arguments, output schemas and
  complete recording consumption are checked. Replayed writes return recorded responses
  without opening connections, sending messages or creating production approvals.
- `live_read_only`: an administrator explicitly authorizes `live_connection_ids` for
  this agent. Authorization and connection status are rechecked during execution.
  Every external write is forbidden, even when the connection allows production writes.
- `human`: fixture execution with an independent human review checkpoint in addition
  to deterministic assertions. A pending review blocks promotion and deployment review.

Assertions support `equals`, `contains`, `gte`, `lte`, `contains_record` and `json_schema`.
The default scope is output; `state` inspects the isolated fork, and `metrics` inspects
observed execution metrics. `tool_sequence` contains actual registered tool names in
execution order. Schema assertions on `$` validate the original output object.

An independently authored order scenario:

```json
{
  "name": "Approved isolated tomato order",
  "split": "regression",
  "source": "synthetic",
  "critical": true,
  "trials": 3,
  "input": {
    "text": "Harbor Bistro: 2 kg Tomatoes",
    "approve_in_test": true
  },
  "assertions": [
    {"path": "total_cents", "op": "equals", "value": 900},
    {"path": "tool_sequence", "value": ["prepare_operation"], "category": "tool_correctness"},
    {"scope": "state", "path": "products", "op": "contains_record", "value": {"sku": "SKU-001", "stock": 148}},
    {"scope": "state", "path": "orders", "op": "contains_record", "value": {"customer_id": "C-001", "total_cents": 900}},
    {"op": "json_schema", "schema": {"type": "object", "required": ["lines", "total_cents"]}}
  ]
}
```

The 148-stock expectation applies to the seeded catalog; each of the three trials
starts at 150. Test approval authorizes only deterministic fictional state mutations.
It never permits external dispatch.

Replay environment example for a configured custom workflow:

```json
{
  "replay": [
    {
      "tool_id": "AUTHORIZED_READ_TOOL_ID",
      "arguments": {"resource": "catalog"},
      "response": {"records": [{"sku": "SKU-001", "stock": 150}]}
    },
    {
      "tool_id": "AUTHORIZED_SEND_TOOL_ID",
      "arguments": {"to": "ops@example.invalid", "subject": "Catalog", "body": "Catalog checked"},
      "response": {"accepted": true}
    }
  ]
}
```

Each tool must already belong to the organization and be authorized by the immutable
AgentSpec. Custom workflows require live mode; local SDK provider-contract tests verify
multi-tool binding and structured output without claiming a real provider response.

Imported data mapping requires an administrator, explicit source model visibility,
an attached connection and declared fields. Only mapped columns enter the fork.
Resources remain private after upload until an administrator authorizes visibility.
CSV numeric fields are converted using the target collection's known fixture types;
JSON object/list fields such as prices and aliases can contain JSON strings.

```json
{
  "data_mappings": [
    {
      "source_id": "EXPLICITLY_AUTHORIZED_DATA_SOURCE_ID",
      "collection": "products",
      "fields": {
        "sku": "product_id",
        "name": "product_name",
        "unit": "unit",
        "supplier_cents": "cost",
        "price_cents": "price",
        "stock": "available"
      }
    }
  ]
}
```

Mapping uses the destination field as the key and imported column as the value.
Visibility or authorization revocation blocks subsequent trials. `state_overrides`
can supply authored local records directly; they never replace the persistent ERP.
State assertions persist selected evidence rather than complete private record sets.

Qualitative grading is optional and requires an explicit rubric:

```json
{
  "criteria": ["Clearly states the customer and requested quantities", "Explains unresolved ambiguity"],
  "threshold": 0.8
}
```

The independent SDK grader has no business tools and records criterion scores/evidence.
Before dispatch it commits a pending UsageRecord linked to the execution and, when build
funded, the build job. Its reservation consumes the run/build budget; a response settles
to observed token estimates. Errors, timeouts and killed workers retain unknown charges
without inventing usage. Worker recovery marks abandoned build reservations uncertain.
Automatic provider HTTP retries are disabled. Rubric accounting commits only isolated
evaluation/read-only grading state; production tool transactions do not use these hooks.
Known run costs are charged once at worker checkpoints/manual retries, and outstanding
reservations remain separate in scorecards and usage metrics. Promotion cost ceilings
include reservations, and unknown charges cannot establish cost savings. Its judgment is
provisional and can reflect evaluator bias. Demo mode or unavailable provider access
leaves the grade pending; no score is invented. Administrators can retry pending
grading with `POST /evaluation-results/{id}/grade` after configuring the provider.
Returning calls recheck build controls/lease ownership and pending result state. An
interleaved retry may retain its observed charge but cannot replace an already resolved
grade. Deterministic failures remain failed. Provider billing reconciliation remains
unavailable, as does full durable accounting for the evaluated agent's own model calls.

Human reviewers submit `{passed, evidence}` to
`POST /evaluation-results/{id}/review`, or use the form under an expanded lab result.
This resolves only the human-review check. Failed arithmetic, output, safety or other
deterministic assertions remain failed. Review is audited and final for that result.
Builds wait for pending reviews and resume from the same completed trial evidence.

Scorecards report per-case repeated-trial pass rates, standard deviation and varying
outcomes, as well as latency, tokens, cost and finite-sample intervals. Trials may be
correlated; passing a small fixture set is not evidence of general business accuracy.
Manual evaluations accept `max_cost` and `max_seconds`; build evaluations inherit
the remaining build budget. Execution and rubric calls use bounded time and cost.
