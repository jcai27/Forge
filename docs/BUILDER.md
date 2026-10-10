# The builder harness

The builder is the part of the factory that improves an agent. It has wide capability and
narrow authority: it can investigate failures, research the public web, write small tools,
draft connections and author the agent's bundle, but every decision that matters stays in
deterministic code or with an administrator. A model proposes; code and people decide.

This document describes what is implemented and how it is verified. See the last section
for what is not verified.

## The search loop

`factory/workflow.py` drives a database-checkpointed state machine. One worker tick does
one stage or one evaluation trial.

- **Parent selection.** After a candidate is rejected the next round branches from the
  best-known version, and the optimizer is shown that version's development failures.
- **Notebook.** `checkpoint["attempts"]` records each candidate's hypothesis, outcome,
  regressed cases and whether it was pruned or rejected before evaluation. The optimizer
  receives it so it does not repeat a failed idea.
- **Rounds.** `Budget.candidates_per_round` (default 1) asks for several proposals from the
  same parent, each with a different strategy. Duplicate proposals are discarded.
- **Screening.** With more than one candidate, the `SCREENING` state runs each on the
  parent's failing development cases plus `Budget.screen_sample` passing ones. A candidate
  survives only if it fixes at least one case, breaks none, and has no critical or safety
  failure. Survivors are fully evaluated in rank order until one is promoted. Screen runs
  have status `screen` and are never used as promotion evidence or by the quality gate.
- **Rejected proposals.** A proposal that names a locked field, reproduces a protected
  case, breaks the code policy or exceeds its turn limit is recorded as a rejected attempt.
  It counts toward stagnation and does not fail the build.

Promotion gates are unchanged and binary. Two additions inform them:

- `graded_score` gives partial credit over case-specific checks and is zero on a safety or
  approval violation. It is reported, not used for promotion.
- A noise guard applies only when repeated trials disagree: the paired per-case improvement
  must exceed one standard error estimated from those trials. Suites with single trials or
  deterministic results behave exactly as before.

## The optimizer

In live mode the optimizer is an SDK agent (`factory/builder.py`, `factory/optimizer_tools.py`).

| Tool | What it returns | Enforced in code |
| --- | --- | --- |
| `list_cases` | Development cases of the parent's evaluation, pass or fail | Tenant, suite, development split |
| `get_case` | One development case: input, outputs, tool sequence, checks | Refused for any other split or tenant |
| `get_tool_contract` | Pinned contract of a tool the version has | Tool must be in the version |
| `get_attempt_history` | The notebook | Tenant |
| `research` | Notes from the public web (when enabled) | See research below |
| `propose_connection` | A drafted connection | See proposals below |

Refused reads are recorded and emitted in an `optimizer_investigation` event. Tool calls are
capped per run, and every model call is reserved and settled through `FactoryBudgetHooks`.

The optimizer returns a `SpecPatch`. It can change `instructions`, `rules`, `output_schema`,
`model`, `examples`, `verifiers`, `tool_notes` and `generated_tools`. Tools, connections,
guardrails, quality policy and resource ceilings are not fields of the patch, and the applied
result is still checked by `enforce_spec_scope`. `BUILDER_MODEL` selects the model for
factory roles and defaults to `OPENAI_MODEL`.

In demo mode the optimizer is still the deterministic two-step rule ladder. It exercises
the loop and gates; it is not evidence that a model improves agents.

## The bundle

Everything the builder authors is executed by the runtime (`factory/runtime.py`).

- **Examples** and **tool notes** are rendered into the model instructions. An example may
  cite a development case in `source_case`. Persisting a version rejects an example that
  cites or reproduces a regression or held-out case.
- **Verifiers** are deterministic checks from a closed vocabulary (`required`, `one_of`,
  `range`, `sum_equals`, `schema`) in `factory/verifiers.py`. They run before a result is
  returned. In live mode a failure earns one repair pass with the failures as feedback.
  A persistent failure sets the run to `needs_attention` and is never staged for approval.
  The output itself is not rewritten.
- **Generated tools** are described below.

## Generated tools and the sandbox

A generated tool is Python that defines `run(input, call)`. It is stored in the version's
spec with a sha256 `code_hash`.

**Where it runs.** Only in the sandbox service (`services/sandbox`). The compose service has
`network_mode: none`, a read-only root, no capabilities, `no-new-privileges`, an unprivileged
user, and process, memory and CPU limits. The worker and API reach it over a Unix socket on a
1 MB tmpfs volume, where the sandbox is the server. It never opens a connection. Each run is
a fresh process with an empty environment, CPU, memory, file-size, process and descriptor
limits, a wall-clock limit, and it is made non-inspectable. Anything a run leaves in the
temp filesystem is removed after it. If `SANDBOX_SOCKET` is unset, generated tools fail
closed; they are never run in-process.

**How it reaches data.** `call(alias, arguments)` does not perform anything. The run stops
and reports the request; the worker performs it through `ExecutionContext.invoke`, the same
path a model tool call takes, and runs the tool again with the result recorded. Replayed
requests must match exactly. So tenant ownership, connection status, contract fingerprints,
redaction, evaluation isolation and replay all apply, and a write is staged as an approval
rather than executed. Each alias maps to a tool the version already has, so generated code
adds no reach.

**Gates.**

1. Static policy (`factory/codepolicy.py`) at persist time: a curated set of standard-library
   names, no file, network or introspection access, a size limit, and a scan for tenant
   credential values and embedded credentials.
2. Isolated evaluation, including the sandbox, before promotion.
3. Provenance: public pages in context when the candidate was written are recorded.
4. Administrator acknowledgement. `POST /versions/{id}/approve` returns
   `code_review_required` listing each tool's name, hash and capabilities until the request
   carries `acknowledged_code` with those hashes. Code already approved for the agent is not
   asked for again. Changed code is.
5. The hash is re-checked before every run.

The static policy is defence in depth and a review aid. It is not the security boundary;
the container is.

`bash scripts/test-sandbox.sh` builds the real image under its own compose project and
checks the isolation: no route, DNS or active interface other than loopback; read-only
filesystem; no capabilities; no credentials in the environment; no application code; and,
assuming the language policy were bypassed, that a run cannot fork, spawn a shell, write
file content, exceed memory, or read the service process.

## Open-web research

Off unless `RESEARCH_ENABLED=true`. Research is a separate agent run
(`factory/research.py`) that receives a question and nothing else.

- The builder has no network. The research step has no tenant data.
- The question, every search query and every URL, including each redirect target, pass an
  outbound screen built from tenant credential values and markers taken from the case
  inputs and outputs the builder has seen. A match is refused and audited.
- Fetches use the pinned public-address transport with a new origin-scoped client per hop,
  https and the default port only, no credentials, bounded bodies and a fetch budget.
- Notes are returned to the builder marked untrusted. Sources are recorded on the candidate.
- Search is offered only when `RESEARCH_SEARCH_URL` is set.

The outbound screen is a strict heuristic over known values and phrases. It is not a
complete data-loss control for unknown private data.

## Connection proposals

A proposal (`factory/proposals.py`) is a drafted REST connection. It holds no credential,
contacts nothing and grants nothing.

- Drafts come from the builder's `propose_connection` tool, from
  `POST /connection-proposals`, or from `POST /connection-proposals/import-openapi`, which
  converts an OpenAPI 3 document deterministically and reports what it skipped.
- Static checks: https only, the single host of the base URL, static relative paths, valid
  JSON Schemas, no credential-like keys, and documented samples consistent with the schemas.
- `POST /connection-proposals/{id}/approve` is administrator-only. The administrator repeats
  the exact hosts, supplies the credential and chooses whether writes are allowed. Only then
  is a connection created, the credential encrypted, and the vendor contacted. A failed
  activation keeps nothing.
- Attaching to an agent creates a fresh version with the new read tools and, like a
  redirection, restarts the build's evidence. Old scorecards are never reused.

## Feedback and release

- `GET /agents/{id}/feedback` lists deployed runs that a person rejected, that needed
  attention, or that failed.
- `POST /runs/{id}/case` turns a real request into an evaluation case. It is
  administrator-only, requires `authorize_data_use`, is audited, and the reviewer supplies
  the assertions. The case has source `production_input`.
- `POST /versions/{id}/shadow` replays recent real inputs through a candidate in evaluation
  mode and compares the answers with the deployed version's. Versions that read external
  systems need `authorize_live_reads`. No approval is created and business state is unchanged.
- `GET /versions/{id}/dossier` gathers what a reviewer needs: reach, generated code and its
  review state, evidence, known failures, research provenance, the shadow report, limits and
  open items.
- The optimizer receives a playbook of hypotheses that were promoted for the same tenant's
  other agents of the same kind.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `BUILDER_MODEL` | empty | Model for factory roles; falls back to `OPENAI_MODEL` |
| `OPENAI_BASE_URL` | empty | OpenAI-compatible endpoint, for example a local model server |
| `OPENAI_API` | `responses` | `responses` or `chat_completions` |
| `OPENAI_STRUCTURED_OUTPUT` | `schema` | `prompt` puts output schemas in the instructions |
| `RESEARCH_ENABLED` | `false` | Enables the research tool |
| `RESEARCH_SEARCH_URL` | empty | JSON search endpoint containing `{query}` |
| `RESEARCH_SEARCH_HEADER` | empty | Optional `Name: value` header for the search endpoint |
| `SANDBOX_SOCKET` | empty | Unix socket of the sandbox; compose sets it |
| `Budget.candidates_per_round` | 1 | Proposals per round |
| `Budget.screen_sample` | 3 | Passing development cases added to a screen |
| `Budget.investigator_turns` | 6 | Tool-use turns for the optimizer; 0 is one-shot |

## Verification

```sh
bash scripts/test.sh          # Ruff, pytest, TypeScript, Vitest, Playwright
bash scripts/test-sandbox.sh  # container isolation of the real sandbox image
```

Backend tests drive the optimizer, investigator, research step and repair pass through the
real Agents SDK loop with local scripted provider transports. Sandbox tests in pytest run the
sandbox server on the host as a fixture: they prove the protocol, the code policy and the
capability path, not container isolation, which `test-sandbox.sh` proves.

## Benchmark

`apps/api/benchmarks/search.py` runs whole builds on the real engine with real agent execution
and grading on the order suite, whose baseline lacks alias and typo handling.

```sh
cd apps/api
.venv/bin/python -m benchmarks.search --seeds 30                      # simulated proposer
EXECUTION_MODE=live OPENAI_API_KEY=... .venv/bin/python -m benchmarks.search --live --seeds 3
```

**Simulated mode** replaces only the optimizer with a seeded proposer that draws from a fixed
pool of seven ideas: two that fix real defects, two that do nothing and three that do harm.
Every arm gets the same kind of proposer, so differences come from the loop. Measured on
2026-10-10, 30 builds per arm, iteration cap 12:

| Arm | Reached target | Full evaluations | Trials | Proposals |
| --- | --- | --- | --- | --- |
| One candidate per round, proposer ignores history | 67% | 8.53 | 244 | 7.5 |
| One candidate per round, proposer uses history | 100% | 6.20 | 182 | 5.2 |
| Three screened candidates per round, uses history | 100% | 4.37 | 176 | 8.6 |

What this shows: giving the proposer its attempt history is the large effect, and it turns
a third of builds from failures into successes at about a quarter fewer trials. Screening cuts
full evaluations by about 30% but total trials by only about 3% on this suite, because the
suite is small enough that a screen costs nearly as much as it saves. Screening should matter
more as suites grow. Every successful build passed all held-out cases.

What this does not show: anything about model quality. The proposer is random by design. All
arms already branch from the best version, so the benefit of that fix is not in this table.

**Live mode** runs the real optimizer through the configured provider. Arms: the one-shot
optimizer, the one-shot optimizer with three times the iterations (so builder spend is
comparable to three proposals a round), and the tool-using harness with three screened
candidates. All arms start from the same authored baseline. `--isolate-builder` executes the
agent under test deterministically, so the builder is the only model in the loop and every
score change is caused by its patch. It refuses to run without `EXECUTION_MODE=live` and a key.

```sh
cd apps/api
set -a; source ../../.env; set +a
EXECUTION_MODE=live BUILDER_MODEL=gpt-5.5 .venv/bin/python -m benchmarks.search --live --isolate-builder --seeds 2
```

### Live results

Measured 2026-10-10 on the OpenAI API with `gpt-5.5` as the builder, `--isolate-builder`,
iteration cap 5, two builds per arm. Cost is the factory's token estimate at
`ESTIMATED_TOKEN_COST`, not an invoice.

| Arm | Reached target, all held-out passing | Evaluation trials | Estimated builder cost |
| --- | --- | --- | --- |
| One-shot optimizer | 2 of 2 | 64 | 0.02 |
| One-shot optimizer, 3x attempts | 2 of 2 | 64 | 0.02 |
| Harness, as first built | 0 of 2 | 182 | 0.90 |
| Harness, after the round-strategy fix | 2 of 2 | 79 | 0.19 |

What happened: a capable model given the evidence and left to its own judgment fixes this
agent in one proposal. The harness as first built did worse, because it told each proposal
of a round which mechanism to use (instructions, then examples, then verifiers). That pushed
the model off the fix it would have chosen: instruction-only changes did nothing and were
pruned, and requested verifiers such as "lines are required" failed correct outputs for cases
that legitimately have no lines, so those candidates regressed. The round now leaves the first
proposal unsteered and asks later ones only to differ from what the round already holds
(`round_strategy` in `workflow.py`). With that, the harness reaches the target in both builds.

What this establishes: the builder works with a capable real model. Model-written patches
were parsed, scope-checked, screened, evaluated, promoted on measured evidence and validated
on held-out cases. A further complete harness build with research enabled also reached the
target with every held-out case passing; the builder read nine development cases, two tool
contracts and the attempt history, and all seven model calls were reserved and settled.

What it does not establish: that the harness is worth its cost. On this task it is not: the
one-shot optimizer gets the same result with fewer trials at about a tenth of the builder
spend. This task has one obvious fix, so it cannot show whether investigation and screening
pay off on harder problems where a first proposal is often wrong. That needs harder task
families, and two builds per arm is far too few to compare arms in any case.

**The newer capabilities, each driven directly by the model in directed exercises:**

| Capability | Result | What was checked |
| --- | --- | --- |
| Open-web research | 3 of 3 runs | The model called `fetch` on https://example.com through the pinned transport over the real internet and reported the page's stated purpose correctly. A question containing customer data was refused before any model or network call. |
| Generated tool | 4 of 4 attempts | The model's code passed the static policy, was pinned by hash in a persisted version, and returned the right answer from a sandbox run. The sandbox here was the host-run service, not the container. |
| Connection draft | 4 of 4 attempts | The model called `propose_connection` with a valid https host and operation. A draft was stored as `proposed`; no connection was created. |

In the complete build above research and connection drafting were available and the model
used neither, which is correct for a task that needs no outside information or new system.
No full build has yet needed them.

Running real models exposed defects that scripted providers could not. All are fixed and
covered by `tests/test_live_provider.py`:

1. Tools were shown to the model under opaque names (`t_<uuid>`). They are now `<name>__<id>`.
2. A template agent stops on its first tool call yet was offered every tool, so one wrong
   choice ended the run. It is now offered only its preparation tool.
3. The preparation tool's schema said only that `input` is an object. The model is now shown
   the agent's own input schema.
4. An empty `OPENAI_BASE_URL=` line in `.env`, once exported by `scripts/dev.sh` or Docker
   Compose, blanked the OpenAI SDK's base URL and every live request failed to connect. The
   client is now always given an explicit base URL.
5. A proposal that timed out, or that carried a malformed JSON Schema, failed the whole build.
   Both are now rejected attempts.
6. A reply that was partly valid was discarded whole. `parse_patch` keeps each field that
   validates on its own, reads only the first complete JSON object, records what it dropped,
   and still refuses a reply naming a field outside the patch.
7. A proposal identical to its already-evaluated parent was fully evaluated again. It is now a
   rejected attempt.
8. A per-proposal strategy travelled only as one key in a large JSON input. It is now also
   stated in the instructions.
9. Prescribing a mechanism per proposal made a capable model worse, as described above.
10. Models key tool notes by tool name; the factory expected the tool id and refused the
    proposal. A name now resolves to its id when exactly one tool of the version has it.

`OPENAI_BASE_URL`, `OPENAI_API` and `OPENAI_STRUCTURED_OUTPUT` allow an OpenAI-compatible
endpoint. They are inactive when empty, which is the default, and all results here are from
the OpenAI API.

One observation is not yet addressed: the model added keys to `rules` that no tool reads
(for example a `normalization_hints` table). `rules` accepts any key, so such additions are
harmless but have no effect, and a reviewer could mistake them for behaviour.

## What is not verified or not built

- The live evidence is one model (`gpt-5.5`), one task family with one obvious fix, and two
  builds per arm (see Benchmark). It shows the builder works; it does not show the harness is
  worth its extra cost, and on this task it is not. Harder task families, workflows over
  custom connectors and a mock vendor API with messy documentation are still needed.
- Research and connection drafting have worked in directed exercises but no full build has
  yet needed them. Generated tools have been written and run by a model, in the host-run
  sandbox service, but not invoked by a deployed agent on a live model.
- `rules` accepts keys no tool reads, so a builder can add settings that do nothing.
- The search endpoint integration is exercised against a local transport only.
- Trials still run one at a time; there is no parallel evaluator pool.
- There is no rerun-to-confirm promotion step and no rotating held-out set, so repeated
  builds on one suite still erode what a held-out pass means.
- Proposals cover REST only, and the REST connector cannot express path parameters.
- New packages for generated tools are not supported; tools use a fixed standard-library set.
- The sandbox image is hardened for Docker with the settings in `docker-compose.yml`. A
  stronger runtime (gVisor, Firecracker or a managed sandbox) is a deployment decision.
- An assertion on path `status` reads the run status and shadows an output field of that
  name. This predates the builder work and is unchanged.
