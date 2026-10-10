# Running real builds

How a build behaves on a real model: what is scored, what it costs, and what happens when
something goes wrong. Code: `apps/api/factory/workflow.py`, `evaluation.py`, `pricing.py`,
`provider_accounting.py`. Tests: `apps/api/tests/test_build_reliability.py`.

## Three sets of examples

| Set | Split name | The builder | Used for |
|---|---|---|---|
| To build from | `development` | reads every row and its failures | diagnosing and improving |
| To check changes | `selection` | never reads; is told only the score | deciding whether a change is kept |
| Held back | `validation` | never reads, never told during the build | the final result |

`regression` cases (must never break again) still exist and are empty for a dataset by
default. When the suite has selection cases, a change is kept only if the score on them
rises and the net gain exceeds its own standard error: one case better is not enough. Before
a version is kept, the selection cases whose outcome changed are run a second time, and a gain
that does not repeat counts for half. The target score is judged on the selection set, so
fitting rules to the rows the builder can see no longer ends a build early.

Each look at the held-back set makes it a little less held back. `held_out_uses` on the agent
counts them, and the build page says so after the third.

## What the builder can use

- Instructions, rules, checks, worked examples, tool notes and small tools, as before.
- `example_pool`: every development case becomes a worked example, copied into the version.
  With more examples than `examples_shown` (default 8, up to 20), each request is shown the
  ones sharing its rarest words. During evaluation a case is never shown its own row.
- `confusions`: counts of what was expected against what was answered across the failures.
- The model can be changed only to one listed in `AGENT_MODELS`. Empty means it cannot.

## Checks that reject correct answers

A builder-written check is a guess; the cases are the truth. Before a version is saved, a
check that a known development answer would fail is removed, with a note in the hypothesis.
A check about a field the answers do not mention cannot be judged that way: it is caught
after one pass, by comparing the answer it first rejected with what the case expects, then
removed and the version measured again before anything is compared.

A pass whose first twenty trials all fail in the same way is cut short.

## When the provider cannot be reached

A dropped connection, a provider timeout, a rate limit or a provider-side error says nothing
about the agent or the builder.

- A trial that hit one leaves no result and is run again. It is never scored as wrong.
- A builder step that hit one is tried again.
- Waits grow from 5 seconds to 5 minutes. After the last, the build pauses with the reason
  and resumes where it stopped. Nothing is lost.
- The failed call keeps its reservation as an unknown charge; the retry is a new call.

The agent's own timeout is not a provider failure and still counts against it. It defaults
to 180 seconds per request.

## Speed

Live trials run side by side (`EVALUATION_CONCURRENCY`, default 8), each in its own database
session, with spend settled under a lock on the build row. On SQLite only agents without
tools run in parallel, because a tool call holds a write open. Hooks release their row locks
before an interruption or a refused reservation propagates: the SDK awaits during cleanup,
and a lock carried across that await deadlocks the other trials.

## Cost

- Replies are not capped (`OUTPUT_TOKEN_LIMIT=0`). A fixed cap cut a reasoning model off
  mid-answer. Time limits and the build budget bound a call.
- `MODEL_PRICES` gives dollars per million tokens as `[input, output, cached input]`. Output
  includes reasoning. A model with no entry uses the flat `ESTIMATED_TOKEN_COST`. The defaults
  are third-party figures: check them against the provider.
- Usage records keep input, cached and output tokens. The build page and
  `GET /builds/{id}` show spend by role.
- `AGENT_REASONING_EFFORT` and `BUILDER_REASONING_EFFORT` request low, medium or high from
  reasoning models.

## Budgets

- Defaults are 25 dollars and 4 hours of active time. Time paused or waiting for a person
  does not count.
- Before each new round the build checks there is room for that round and for the final
  held-back measurement, counting what each call sets aside up front. If not, it stops
  improving and spends what is left on the measurement.
- A build that reaches the end with its best version under the target ends `BELOW_TARGET`.
  `FAILED` means something broke.

## Modes

`EXECUTION_MODE=hybrid` runs the built-in templates on their fixtures, free, and custom agents
on the real model. Every run records the mode it used.

## The score required for approval

Set when the agent is created (`minimum_score`, the create form's "Score required for
approval"). The build aims for it and a version below it cannot be approved. No builder role
can change it.

## From the command line

```bash
cd apps/api
EXECUTION_MODE=live .venv/bin/python -m benchmarks.task_build \
  --task "Route each customer message to the right banking support queue." \
  --data https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv \
  --development 150 --selection 100 --validation 100 --max-cost 40 --baseline \
  --state /tmp/banking-run
```

With `--state` the run is kept. Run the same command again to resume one that was stopped or
paused.

## Not done

- Customer rows are stored as test cases unencrypted. Use database or disk encryption.
- The price table has two models. Others are priced at the flat rate until added.
- Parallel trials for tool-using agents on SQLite.
- The held-back set does not rotate; it is only counted.
