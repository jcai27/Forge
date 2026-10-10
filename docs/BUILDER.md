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

**Live mode** compares the one-shot optimizer with the tool-using harness on the same task
using a real provider. Both arms start from the same authored baseline, so only the optimizer
differs. It refuses to run without `EXECUTION_MODE=live` and a key.

### Live results with the only real model available here

No OpenAI key is configured. A local `llama3.2:3b` under Ollama was the only real model on
this machine, reached through its OpenAI-compatible endpoint (`OPENAI_BASE_URL`,
`OPENAI_API=chat_completions`, `OPENAI_STRUCTURED_OUTPUT=prompt`). Measured on 2026-10-10,
two runs of two builds per arm, iteration cap 4:

| Role | Result |
| --- | --- |
| As the deployed agent | Baseline pass rate 0.57 to 0.79 across eight builds of the same version, so the same agent varies by about 20 points run to run. Seven of eight baselines had a critical failure. |
| As the builder, one-shot | Every reply was an invalid patch and was rejected. No candidate was ever evaluated. |
| As the builder, harness | Every reply was an invalid patch and was rejected. No candidate was ever evaluated. |

What this establishes: the whole pipeline runs with a real model. Provider calls, per-call
reservation and settlement, real agent execution inside evaluation, and the rejection of
malformed proposals all worked, and no build crashed on bad model output.

What it does not establish: whether the builder helps. This model cannot act as a builder at
all. It wraps its answer in an extra object, emits invalid JSON and fills every field with
junk, so neither arm produced a single candidate and the comparison is empty. That needs a
capable model, and none is available here: no API key, and 1.5 GB of free disk rules out a
larger local model.

Running a real model also exposed five defects that scripted providers could not, all fixed:

1. Tools were shown to the model under opaque names (`t_<uuid>`), so it had to choose from
   descriptions alone and chose wrongly. Tools are now named `<name>__<id>`.
2. A template agent stops on its first tool call, yet it was offered every tool, so one wrong
   choice ended the run. It is now offered only its preparation tool. The local model went
   from zero correct runs in three to three in three.
3. The preparation tool's schema said only that `input` is an object, and the model sent
   junk. The model is now shown the agent's own input schema.
4. The factory could only reach api.openai.com. `OPENAI_BASE_URL` and `OPENAI_API` now select
   an OpenAI-compatible endpoint, and every live call goes through the configured client.
5. This server rejected the larger output schemas ("failed to parse grammar").
   `OPENAI_STRUCTURED_OUTPUT=prompt` puts the schema in the instructions; replies are
   validated in code identically in both modes. Separately, a proposal that timed out failed
   the whole build; it is now a rejected attempt.

To run it with a capable model:

```sh
cd apps/api
EXECUTION_MODE=live OPENAI_API_KEY=... .venv/bin/python -m benchmarks.search --live --seeds 3
```

## What is not verified or not built

- Whether the builder helps is unmeasured. The only real model available, a local 3B model,
  cannot produce a valid patch, so the live comparison produced no candidates (see Benchmark).
  A capable model is needed. The live benchmark covers one task family; workflows over custom
  connectors and a mock vendor API with messy documentation are still to add.
- Research, generated tools and connection drafts have not been exercised by any real model.
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
