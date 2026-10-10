# Agent Factory: product brief for agents

Read this before starting work in this repository. It tells you what the product is for,
what the finished product does, what exists today, and what to build next.

Precedence when documents disagree:

1. `AGENTS.md`: engineering rules and invariants. Never violate these.
2. `docs/AGENT_FACTORY_SPEC.md`: the original acceptance criteria.
3. This file: direction and priorities.
4. `PLANS.md` and `docs/PROGRESS.md`: current status and evidence. `docs/BUILDER.md`
   describes the builder in detail.

Status words used below have fixed meanings:

- **VERIFIED**: covered by automated tests that pass, or measured with a real model.
- **DIRECTED ONLY**: worked when a real model was explicitly told to do it. Never yet needed
  or chosen inside a full build.
- **UNMEASURED**: built, but there is no evidence it helps.
- **NOT BUILT**: does not exist.

## 1. Business goal

Agent Factory is a platform that builds specialized AI agents for real business operations
and proves that each one works before it is deployed.

The value to a customer is this: they describe a job in plain language, hand over their data
or tell us where it lives, and receive an agent that does the job, with measured evidence of
how well it does it and human control over anything that changes their systems.

Two things make it a business and not a demo:

- **The builder does the engineering.** A person should not have to write prompts, hand-wire
  integrations or hand-write tests to get a working agent.
- **The evidence is trustworthy.** An agent is promoted only on measured results against
  tests the builder could not see. A customer can rely on a score.

**Market, as stated by the owner:** business operations use cases, broadly. The owner is open
to a narrower or stronger focus if the evidence supports one.

**Working focus, proposed and not yet confirmed by the owner:** operations work that turns an
incoming request into a correct record in a system. Examples: order entry from emails,
quoting from price lists, invoice and accounts-payable processing, support-message triage,
scheduling and follow-up. Prefer these when choosing benchmark tasks and connectors, because:

- Each has a checkable right answer, which is what the factory's evidence depends on.
- Mistakes cost money, so approval gates and measured accuracy are worth paying for.
- They need exactly what the factory does: reading a business system, applying rules,
  proposing a write for approval.
- Two of the three built-in templates (orders, quotes) are already this shape.

Deprioritise open-ended work with no checkable answer, such as research summaries or content
writing. The factory cannot prove such an agent is good, so its main advantage does not apply.

**Delivery model, decided by the owner:** a service. The owner runs builds for customers.
The customer does not operate the factory. What this means for your work:

- **The operator is the user.** The person driving the app is the owner or their team, an
  expert who runs many builds. Optimise for their speed and for seeing exactly what a build
  did. Self-serve onboarding, guided setup and consumer polish are low priority.
- **Each customer is a tenant.** The owner works across many organizations. Tenant isolation
  is what keeps one customer's data, credentials and playbook away from another's. Treat any
  cross-tenant leak as the most serious class of defect.
- **The release dossier is a deliverable.** It is what the owner shows a customer to justify
  an agent. It must be accurate, readable by a non-engineer, and honest about limits.
- **Builder cost is the owner's cost of sales.** Token spend per build comes out of margin.
  Report it accurately, keep the cheapest approach that works, and do not add builder
  machinery that has not shown it pays for itself (see P5).
- **Repeatability compounds.** The same operations jobs recur across customers. Anything that
  makes the second customer's build faster than the first is valuable, within tenant rules:
  reusable connectors, benchmark task families, and operator tooling. A customer's data and
  what was learned from it stay in that customer's tenant.

**Customer access, decided by the owner:** the customer gets their own login. Its purpose is
to let the customer approve what the agent does to their systems. The owner still runs the
builds.

**Credentials, decided by the owner:** the customer hands credentials to the owner, and the
owner enters them into the factory. Consequences:

- The owner is a custodian of customer secrets. Credentials go only into the encrypted secret
  field. Never put one in a prompt, a config value, a test, a log, a commit or a chat.
- Ask customers for the narrowest credential that works: read-only where the agent only
  reads, scoped to the tables or endpoints it needs.
- When an engagement ends or a credential is rotated, use the existing revocation path, which
  retires the secret and keeps historical redaction working.

Not yet decided by the owner, so do not assume: who the first customer is, pricing, which
industries come first, and exactly what a customer login may see and do. See section 8.

## 2. The finished product

The owner's target experience, in their words: you give the agent a task, plus the data or
instructions on how to access the data, and it does all the steps from there.

Concretely, a finished build goes like this:

1. **Input.** The user gives one or more of: a task in plain language; data files, with or
   without correct answers in them; instructions for reaching a system (a database, an API).
2. **Understand.** The builder works out what the agent must do and what it needs.
3. **Research.** Where the task depends on outside knowledge (a vendor's API, a data
   format), the builder reads public documentation.
4. **Connect.** The builder sets up the connections the agent needs: databases, APIs, files.
5. **Build.** The builder writes the agent: instructions, worked examples, checks on its
   output, and small code tools where a deterministic step beats asking a model.
6. **Test.** The builder turns the provided data into test cases, or writes test cases when
   none are provided, and keeps a held-out set it never sees.
7. **Improve.** It evaluates, diagnoses failures, changes the agent, and keeps only changes
   that measurably help without breaking what worked.
8. **Hand over.** The user receives one pinned version with a dossier: what it can reach,
   how it measured, what is still uncertain. They approve, and it is deployed.

The builder is a real agent harness with wide capability and narrow authority. It can
investigate, research, write code, draft connections and author the agent. It never holds a
credential, never grants itself access, never sees held-out answers, and never decides its
own promotion. Those belong to deterministic code and to people.

Human steps that remain in the finished product, on purpose:

- Supplying credentials. Secrets never enter a model's context.
- Approving access to a new system or host.
- Approving test material, which may be one approval for a whole dataset.
- Approving a version for deployment, including any code the builder wrote.
- Approving each write to a business system.

Everything else should need no human. Because this is a service, the owner as operator does
most of these: entering credentials the customer hands over, approving access, test material
and deployment. The customer approves writes to their own systems through their own login.

Owner preferences that are settled:

- Use the strongest available model for both the builder and the deployed agent, unless
  speed matters for the use case.
- The builder may write code, inside the sandbox only.
- The builder may research the open web.
- Do not use local models. Use the hosted provider key in `.env`.

## 3. What exists today

On `main`. See `docs/BUILDER.md` and `docs/INTAKE.md` for detail and `docs/PROGRESS.md` for
evidence.

### Platform (predates the builder work)

| Capability | Status | Where |
| --- | --- | --- |
| Web app, API, background worker, database-backed resumable jobs | VERIFIED | `apps/web`, `apps/api`, `services/worker` |
| Immutable agent versions, tenant isolation, roles | VERIFIED | `apps/api/factory/models.py`, `api.py` |
| Connectors: REST, PostgreSQL, file, webhook, email, MCP | VERIFIED locally, not against real vendors | `factory/connectors.py` |
| Isolated evaluation with development, regression and held-out splits | VERIFIED | `factory/evaluation.py` |
| Deployment, invocation queue, approval of every write | VERIFIED | `factory/deployment_runtime.py`, `runtime.py` |
| Cost reservation before every model call | VERIFIED | `factory/provider_accounting.py` |

### Builder

| Capability | Status | Where |
| --- | --- | --- |
| Search loop branches from the best version, remembers attempts, guards against noise | VERIFIED | `factory/workflow.py` |
| Optimizer is a tool-using agent that reads only development cases | VERIFIED, including with `gpt-5.5` | `factory/optimizer_tools.py`, `builder.py` |
| Typed patch: the builder cannot name tools, connections, guardrails, policy or ceilings | VERIFIED | `factory/schemas.py` `SpecPatch` |
| Several candidates per round with cheap screening | VERIFIED mechanically, UNMEASURED as a benefit | `factory/workflow.py` `SCREENING` |
| Examples, tool notes and output verifiers, all executed by the runtime | VERIFIED | `factory/runtime.py`, `verifiers.py` |
| Code tools run in a sandbox with no network or credentials | VERIFIED isolation (36 container checks) | `services/sandbox`, `factory/sandbox.py` |
| A model writes a tool that passes policy and runs in the sandbox | DIRECTED ONLY | `factory/codepolicy.py` |
| Open-web research, isolated from customer data | DIRECTED ONLY | `factory/research.py` |
| Drafting a REST API connection for administrator approval | DIRECTED ONLY | `factory/proposals.py` |
| OpenAPI document to connection draft | VERIFIED | `factory/proposals.py` |
| Shadow comparison, release dossier, test case from a real run, tenant playbook | VERIFIED | `factory/release.py` |
| Benchmark that runs whole builds | VERIFIED | `apps/api/benchmarks/search.py` |

### Build inputs (2026-10-10)

- A build takes a task, business context documents and a source of truth. Without examples
  that have correct answers, or a recorded statement that the task needs none, a build is
  refused.
- A dataset (uploaded, or fetched from a public https address) becomes evaluation cases. The
  platform splits it; the builder sees the development part and never the held-out part.
- Context documents are read by the builder only: in its requests and through paged
  investigator tools.
- A custom agent may have no tools and work from its input alone.
- A build that runs out of rounds still reports its best version's held-out score.
- `benchmarks/task_build.py` runs a whole build from a task and a data address, and resumes.
- Real-model behaviour is in `docs/RUNNING_BUILDS.md`: three sets of examples, retries,
  parallel scoring, pricing, budgets and end states.

### What the evidence says

- With `gpt-5.5` as builder, the factory fixed the benchmark agent (0.75 to 1.00) and passed
  every held-out case. The builder works end to end with a real model.
- On that one task the plain one-shot optimizer did equally well at about a tenth of the
  builder cost. The multi-candidate harness has **not** shown it is worth its cost.
- The benchmark task has one obvious fix. It cannot tell us how the builder does on hard tasks.
- No build has yet gone from "a task and some data" to a deployed agent without a person
  preparing connections and test cases by hand.

## 4. The gap

Compare section 2 with section 3. A build now starts from a task, documents and data, and
reports a held-out score. What is missing: a real build on a strong model at a size that
means something, examples and context taken from a customer's own systems, and the customer's
own login.

## 5. What to build, in priority order

Each item has a definition of done. Do not mark one complete without running its checks.

### P1. Provided data becomes test cases: done

Built as described in `docs/INTAKE.md`. Two decisions differ from the first plan, both by the
owner. Data is the source of truth, so its cases count as evidence without a per-batch
approval; drafted cases with no data behind them still wait for review. And there is no
regression part by default.

Checked by 38 tests, including a whole build that asserts no held-out row reaches any builder
request, and one browser journey.

### P2. Agents without tools: done

A custom agent with zero tools is created, evaluated and improved, and approved through the
unchanged quality gate. Tool permission checks are unchanged for agents that have tools.
Not checked: deploying and invoking such an agent in production.

### P3. One task-plus-data build, end to end: run, result negative so far

Run on OpenAI with `gpt-5.5` as builder and agent, from one sentence and the public Banking77
test file (3,080 rows, 77 queues; the publisher's repository states CC BY 4.0, confirm before
reuse), 60 rows to build from and 60 held back, 12 minutes, about 4.90 dollars. The first
version scored 85% on held-back rows and the builder's version 83%. The builder did not
improve the agent: it fitted the rows it could read. See `docs/PROGRESS.md`.

In response the build now scores every change on rows the builder never reads, and the
builder has an example pool and a summary of what is confused with what
(`docs/RUNNING_BUILDS.md`). Whether that makes the builder add value is not yet measured.

Still to do: one clean `gpt-5.5` run at 150/100/100 with a budget the owner sets, and an
honest report of first against final held-back score, spend, and every point where a person
had to act. If the result is again flat, the builder's value on tasks like this has to come
from business context, tools and connections, and the benchmark should move to a task that
needs them.

### P4. Database connections from instructions

Problem: the builder can draft REST connections only.

Build: extend proposals to PostgreSQL. From instructions naming a schema and tables, the
builder drafts a read-only connection. The administrator supplies the credential in a secret
field and approves. Optionally, an administrator pre-authorizes a stored credential so the
builder may create read-only connections to that database without a further approval.

Before building, read the PostgreSQL connector's network path. It does not use the pinned
public-address transport that REST and MCP use, databases usually sit on private networks,
and `PLANS.md` lists PostgreSQL transport bounds as unfinished.

Done when: the credential never enters a model context or a proposal row; write access always
needs a person; a pre-authorized builder can attach only the tables the administrator listed.

### P5. Learn whether the harness is worth its cost

Build harder benchmark task families where a first proposal is often wrong: P3's triage
task, a workflow over a custom connector, and a mock vendor API with messy documentation.
Compare the one-shot optimizer with the harness at equal builder spend, with enough builds
per arm to tell them apart.

Done when: `docs/BUILDER.md` states, with numbers, on which kinds of task the harness beats
the one-shot optimizer, or that it does not. Either answer is acceptable. If it does not,
simplify the builder.

### P6. Research, code tools and connection drafts inside a real build

These are DIRECTED ONLY. P3 to P5 should produce a build that needs each of them. Until one
does, do not claim they work in practice. Also still open: a generated tool being invoked by
a deployed agent on a live model, through the container sandbox.

### P7. A customer login that can approve and nothing more

Required before any customer's agent goes live. It does not depend on P1 to P6, so schedule
it by when the first customer deployment is expected.

Problem: the roles today are `admin`, `editor` and `viewer`, and approving a write requires
`admin` (`/approvals/{id}/resolve` calls `require_admin`). A customer who must approve writes
would therefore need `admin`, which also lets them change connections, approve versions,
deploy, revoke credentials and manage members. That is far too much.

Build: a customer role, for example `approver`, limited to its own organization. It can see
pending approvals with the exact proposed action, approve or reject them, and see the runs
and the release dossier behind them. It cannot see or change connections, credentials,
versions, builds, test cases, budgets or members. Invitations and session switching already
exist and should be reused.

Done when: an approver can resolve an approval in their own organization and is refused, by
server-side checks with tests, on every other write route and on every other organization;
the permission recheck at the write boundary accepts the approver role; the approvals screen
is usable by a non-engineer and explains each action in plain language; every decision is
audited with who made it.

### P7a. Inputs from the customer's own files and systems

Context documents are text only, and examples come from a file or a public address. Build:
PDF, Word and spreadsheet intake; examples read from a customer connection (with P4) under
explicit authorization; a way to replace a dataset.

### P8. Smaller defects and limits

- The price table holds two models; others are priced at one flat rate per token.
- Customer rows are stored as test cases unencrypted.
- The held-back set is counted but does not rotate.

- `rules` accepts keys no tool reads, so a builder can add settings that do nothing. Reject
  or flag them.
- Evaluation runs one trial at a time. Add bounded parallel execution.
- No rerun-to-confirm before promotion, and the held-out set is reused across builds.
- The REST connector cannot express path parameters.
- Generated tools use a fixed standard-library set. No reviewed third-party packages.
- The sandbox is hardened for Docker. Production may need gVisor, Firecracker or a managed
  sandbox. This is a deployment decision for the owner.
- The build timeline lags about two seconds behind a finished build before "Load more" appears.
- An assertion on path `status` reads the run status and shadows an output field of that name.

## 6. Rules you must not break

The full list is in `AGENTS.md`. The ones most relevant to this roadmap:

- Tenant ownership is checked server-side on every resource access.
- Secrets never enter model context or browser responses.
- Held-out and regression answers never reach the builder: not in payloads, tool replies,
  examples or the attempt notebook. Enforce by case identity in code, not by prompt wording.
- Versions are immutable. A new capability means a new version and fresh evaluation.
- Production writes require explicit human authorization.
- Generated code runs only in the sandbox, holds no secrets or network, reaches systems only
  through brokered capabilities, and is pinned by hash. Never add an in-process fallback.
- A draft or proposal never grants access. Only an administrator does.
- Promotion requires measured, regression-safe evidence. A better-looking prompt is not evidence.
- Tests exercise behaviour and security boundaries. Never write a test that overrides a score.

## 7. How to work here

Setup and commands:

```sh
bash scripts/dev.sh           # local API, worker and web
bash scripts/test.sh          # Ruff, pytest, TypeScript, Vitest, Playwright
bash scripts/test-sandbox.sh  # isolation of the real sandbox image; needs Docker
```

PostgreSQL tests, in isolated per-test schemas:

```sh
TEST_DATABASE_URL=postgresql+psycopg://factory:local-factory-password@127.0.0.1:55432/factory \
  apps/api/.venv/bin/python -m pytest apps/api/tests -q -c apps/api/pyproject.toml
```

Live benchmark, which spends real money on the key in `.env`:

```sh
cd apps/api && set -a && source ../../.env && set +a
EXECUTION_MODE=live BUILDER_MODEL=gpt-5.5 .venv/bin/python -m benchmarks.search --live --isolate-builder --seeds 2
```

Working rules learned the hard way on this project:

- **Real models find what fakes cannot.** Scripted providers passed every test while a real
  model could not pick the right tool. Run a real model before claiming a model-facing
  feature works.
- **Report the unflattering result.** The harness looked better than the one-shot optimizer
  until spend was equalized and a capable model was used. Equalize spend, state sample sizes,
  and say when a difference is not distinguishable.
- **Keep `EXECUTION_MODE=demo` in `.env`.** With `live` there, the test suite and dev server
  make billed calls. Turn live mode on per command.
- **Start live runs small** and report token spend before scaling up.
- **No local models.** Loading one beside the Compose stack filled the host disk and hung
  Docker. Check free disk before building images.
- **Store checkpoints as fresh copies.** Reassigning an edited dict after an autoflush loses
  the edit.
- **Catch `PermissionError` before `OSError`.** It is a subclass; a denied capability must
  never be reported as an outage.
- Update `PLANS.md` and `docs/PROGRESS.md` after each verified milestone. Do not declare a
  phase complete without executing its checks.

## 8. Open questions for the owner

Ask before assuming an answer to any of these.

1. The market is operations, broadly. Is the working focus in section 1 (requests turned into
   correct records) the right first wedge, and who is the first customer? This decides
   which connectors and benchmark tasks matter.
2. The customer has their own login to approve writes (P7). Beyond approvals, what may a
   customer see: runs, the dossier, evaluation results, cost? Can the owner also approve on a
   customer's behalf, for example during setup?
3. How much may a single build spend by default? Today it is 5 dollars of estimated spend.
4. Which human approvals may be collapsed into one, and which must stay separate?
5. May the builder be pre-authorized to connect to a customer's database read-only (P4)?
6. Keep the multi-candidate harness if P5 shows it does not pay for itself?
7. Keep the OpenAI-compatible endpoint option, given that local models are not wanted?
8. Are the three built-in templates (orders, quotes, hiring) a product feature or only demos?
9. What sandbox runtime is acceptable for production?
