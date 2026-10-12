# Agent Factory engineering instructions

The authoritative acceptance criteria are in docs/AGENT_FACTORY_SPEC.md.
Architecture: Next.js frontend (apps/web), FastAPI/SQLAlchemy backend (apps/api),
database-backed resumable worker (services/worker), reusable integrations.
Use Python 3.12+, uv, strict TypeScript, pnpm, Alembic, pytest, Ruff, Playwright.
Commands: bash scripts/dev.sh (local API/worker/web); bash scripts/test.sh
(Ruff, pytest, TypeScript, Vitest, Playwright); corepack pnpm --filter @factory/web build.
Docker: docker compose up --build. Local infrastructure uses isolated project
agent-factory and ports 55432/56379. Tests can use TEST_DATABASE_URL with fresh schemas.
Consult README.md for exact setup and docs/PROGRESS.md for evidence and remaining work.
Workspace access is documented in docs/ACCESS.md. Invitations store only token hashes;
return the code once, never expose hashes or record raw codes in audits. Acceptance must
match the signed-in email, require a current inviting administrator and a pending grant,
and never upgrade an existing membership. Serialize administration/acceptance on the
organization in PostgreSQL, then recheck the actor's current role. Preserve self-admin
access and existing-token revocation; clear browser caches on authentication changes.
Worker leases and queued invocations are database-backed. Recovery tests kill real
processes; PostgreSQL-only tests verify concurrent approvals and invocation idempotency.
DEV_API_PORT/DEV_WEB_PORT allow isolated local startup alongside Compose.
Evaluation environments and case formats are documented in docs/EVALUATIONS.md.
Pending human/rubric reviews halt promotion; reviews preserve deterministic failures.
Replay must never instantiate a live adapter. Imported mappings require explicit
administrator/model-visibility authorization and select only declared fields.
Builder policies/accounting are documented in docs/FACTORY.md. Live architecture runs
in the worker; model candidates cannot change user quality policies or expand resource
ceilings. Role usage records use job_id and a nullable run_id; runtime/grading records
use run_id. Factory model calls commit pending UsageRecords/reserved_cost before dispatch;
observed responses settle them, unresolved calls retain uncertain reservations in the
build budget. Do not count reserved_cost as observed token usage or billing. Preserve
pause/cancel and lease ownership when committing results after provider I/O.
Read-only rubric calls also commit pending run/job UsageRecords before dispatch, retain
unknown reservations, disable hidden HTTP retries and settle observed usage independently
of grade validity. build_accounted_cost prevents charging observed run costs twice.
Manual grading rechecks the pending result after I/O; competing calls retain both charges
but publish one grade. Include reservations in budget ceilings, never in observed cost
or tokens; unknown charges cannot prove a cost improvement. Do not reuse grading hooks
for production tool transactions. Queued deployment execution uses its own durable
deployment_agent ledger: reserve inside the queue allocation before dispatch, retain
unknown charges on interruption, and settle observed costs once. Model/tool checkpoints
recheck current membership, pinned approved version, deployment and lease ownership.
Keep final approvals/result/queue settlement in one transaction. A late stale response
may settle usage but cannot publish another result. Public production execution must enter the deployment queue. Direct execute is an
internal helper, with no standalone API endpoint. Do not expose a new production entry
point without durable accounting and current authorization, or reuse evaluation hooks. Live evaluated-agent calls now use evaluation_agent ledgers
and control checks at model/tool boundaries. Recover abandoned calls as uncertain and
mark their orphaned execution failed; rerun only within the remaining build budget.
Production connector write requests stay staged in ExecutionContext until final output
validation succeeds. Do not attach them to the SQLAlchemy session during model/tool
checkpoints. Publish pending approvals with the validated execution result; failures must
expose no new actionable approval. Approval dispatch rejects queued/running/failed runs,
while authorized rejection remains available for stale requests.
Collection traversal uses bounded pages. Keep paged query keys separate from single-page
resource keys; preserve loaded selector options and use type="button" for load controls
inside forms. Never silently stop at a server's default first page. Scale polling with
loaded pages rather than multiplying request rates. Remaining secondary/history lists
are documented in PLANS.md and must not be called fully audited.
Build event streams must coalesce query refreshes instead of refetching once per event.
Preserve the event cursor and cancel queued refreshes on unmount. Browser acceptance
checks include zero HTTP 429 responses; do not raise/disable API limits to pass them.
Proposal browser fixtures use a local SDK model and actual worker review checkpoints,
never seeded scores or a production-only test endpoint.
Read PLANS.md's current priorities rather than older progress snapshots.
Build redirection requires a fresh immutable version/evaluation and retains global
time/cost/iteration limits. Never reuse previous scorecards for a revised objective or
allow a stale returning worker to overwrite the redirected checkpoint.
Generated test proposals are not evidence: keep them outside evaluation_cases until
administrator correction/acceptance. No proposed plan can grant live/imported access.

Credential filtering is documented in docs/SECRET_BOUNDARIES.md. Apply tenant-scoped
known-value filtering at model/tool/output/browser boundaries. Retired ciphertext is
redaction-only and must never be used for connector authentication or exposed by APIs.
Preserve historical filtering when removing or rotating active credentials.

REST response handling must bound wire and decoded bytes during streaming, including
compressed bodies. Keep total HTTP deadlines and close discarded streams. Never retry
HTTP write methods automatically; uncertain results go through reconciliation.
REST/MCP egress uses origin-scoped pinned transports: validate every DNS result, connect
to numeric public IPs and preserve original HTTP/TLS identity. Do not replace this with
preflight DNS followed by an ordinary client connection, enable environment proxies or
redirects, or permit private/transition destinations. MCP 2 requires native httpx2
transport/stream types and snake_case SDK attributes. Loopback remapping and custom
test certificates are owned-test-fixture dependencies, never user configuration.
MCP responses share wire/decoded limits across a client session, before JSON/SSE parsing.
Keep bounded decompression, pagination limits and whole-operation deadlines. An exhausted
decoded budget must never reach zlib with max_length=0 (which means unlimited output).
Do not enable automatic tool-call retries or expose resource ceilings as server overrides.

The builder harness is documented in docs/BUILDER.md. The optimizer is a tool-using SDK
agent that returns a typed SpecPatch of mutable fields only; locked fields (tools,
connections, guardrails, quality policy, ceilings) are not in the patch model and the
applied result is still scope-checked. Investigator tools expose only this tenant's
development split by case identity; keep regression/held-out answers out of every
builder payload, tool reply, example and notebook entry. The search loop always branches
from the best-known version, never from a rejected candidate. Store checkpoints as fresh
copies (deepcopy): reassigning an edited dict after an autoflush loses the edit. Screen
runs have status `screen`/`screening` and are never promotion evidence. A proposal that
breaks its contract is a rejected attempt, not a failed build.

Builder-written code is allowed only as `generated_tools`, and only under these rules:
it runs in the sandbox service (services/sandbox), never in the API or worker process;
the sandbox has no network, credentials or host disk and is reached over a Unix socket
where it is the server; code reaches systems only by capability calls that the worker
performs through ExecutionContext.invoke, so tenant, contract, approval and redaction
checks apply; writes are staged as approvals, never executed by code; code is pinned by
sha256 in the immutable version and re-checked before every run; an administrator must
acknowledge each new code hash before a version is approved. factory/codepolicy.py is
defence in depth and a review aid, not the boundary; the container is. Never add an
in-process fallback when SANDBOX_SOCKET is unset. Catch PermissionError before OSError:
it is a subclass, and a denied capability must never be reported as an outage. Run
`bash scripts/test-sandbox.sh` after changing the sandbox image, runner or compose service.

Open-web research (factory/research.py) is off unless RESEARCH_ENABLED=true. It is a
separate agent run that receives only a question; the question, search queries and every
URL including redirect targets pass the OutboundScreen (tenant credential values and
markers from evidence the builder has seen). Fetches use the pinned transport with a new
origin-scoped client per hop, https and the default port only, and bounded bodies. Fetched
text is untrusted data. Do not give the research step tenant data or the builder a network.

Connection proposals (factory/proposals.py) hold no credential and contact nothing. Only
administrator approval, with the exact hosts repeated back, creates a connection; the
credential exists only there, encrypted. Attaching a connection creates a fresh version
and resets build evidence exactly as redirection does. Production input becomes a test
case only through the audited, administrator-only /runs/{id}/case with explicit
authorization, and the reviewer supplies the expectation. Shadow runs execute in
evaluation mode and must create no approval and change no business state. The playbook
and the investigator ledger are tenant-scoped.

Build inputs are documented in docs/INTAKE.md. A build needs a source of truth: cases on
both the development and held-out side, or a recorded no_data_reason; never start one with
neither. Datasets are split in code (factory/intake.py), never by a model, and a row already
in a suite is never imported again in another split. Dataset profiles shown to the builder
hold development rows only. Schemas derived from data are pinned: no designer may change
them. Context documents go to builder roles and the investigator's read_context only, never
to the deployed agent, and their text joins the research outbound screen. Dataset addresses
use the pinned transport with a new origin-scoped client per hop. PDF input is text read once at the
boundary by factory/documents.py: bounded bytes, pages and characters, and a page with no text
layer (a scan) is refused by name, never passed on as empty. A zip of examples holds one table and
the PDFs its cells name; check declared sizes before unpacking and bound every read. No PDF byte
or file name is stored in a case. Scanned pages and photos are read by a model only through
factory/reading.py and only when DOCUMENT_READING is on: commit a pending document_reader
UsageRecord before each page leaves, settle it on the reply, keep an unanswered call's reservation
as uncertain and never retry it; check the upload's ceiling before every page; keep each reading
per tenant under a hash of image, model and instructions and bump INSTRUCTIONS_VERSION when the
instructions change. A page image cannot be credential-filtered; the returned text always is. A custom agent with no
connection may have no tools; tool_correctness is graded only when tools were offered. A
build stopped at its round limit measures its best version on held-out cases and still ends
BUDGET_EXHAUSTED; that measurement is a report, not a pass. The browser keeps one query
cache per tab and does not refetch /auth/me after unrelated actions: the browser suite runs
close to the API request limit, so count requests before adding polling or blanket refreshes.

Real builds are documented in docs/RUNNING_BUILDS.md. Selection cases are scored on every
pass and never shown to a builder role: only the aggregate unseen_score. Keep a version only
on a net selection gain beyond its standard error, after its changed selection cases have run
twice. A provider failure (connection, provider timeout, rate limit, 5xx) is never scored
as a wrong answer and never fails a build: the trial leaves no result and is rerun, the step
is retried with growing waits, then the build pauses with resume_state. The failed call
keeps its reservation; the retry is a new call. Parallel trials each use their own session
and settle spend under the build row lock; a hook must commit before raising
BuildInterrupted or BudgetExceeded, because the SDK awaits during cleanup and a row lock
carried across that await deadlocks every other trial in the process. Nothing may be left
uncommitted across a provider call in a live evaluation. Paused and waiting time is tracked
in idle_seconds and is not the build's time. Before a round, keep room for it and for the
final held-out pass including up-front reservations. BELOW_TARGET is a finished build under
its target; FAILED means something broke. Replies are uncapped unless OUTPUT_TOKEN_LIMIT is
set; hooks' max_output_tokens is a reservation allowance, not a limit. Price usage through
factory/pricing.py only. A builder may change the agent's model only to one in AGENT_MODELS.
Remove verifiers that reject known development answers before saving a version; never judge
a verifier against selection or held-out answers. With example_pool the examples are the
development cases only, and in evaluation a case is never shown its own row. The builder's instructions (architect_prompt, optimizer_prompt) state how work
is judged and what each option does and costs. They never recommend an option: advice
written from one task's result would be applied to every task. Include tool, document and
code sections only when the agent has those. Resolve demo or
live per agent with mode_for(template), not settings().execution_mode. The browser suite
cannot run while `next dev` is already running in apps/web.

The customer side is documented in docs/CUSTOMERS.md. A customer works in an organization of
its own (kind "customer"), opened by a builder who stays its administrator. An installed agent
is a copy of one approved version with its own deployment; never share a deployment, a case or
an evaluation across organizations. The `customer` role reaches /portal/*, /auth/* and invitation
acceptance only, enforced in security.principal; keep new builder endpoints outside those paths
and new portal endpoints tenant-checked with `owned`. Portal documents run through the ordinary
deployment queue as the member who installed the operation. Mailboxes: TLS on 993, read-only,
only mail after the recorded position, public addresses only with the certificate checked
against the name; passwords and webhook keys encrypted, inbound keys stored as hashes and shown
once. A webhook delivery is made once, on approval, and never retried. What happens to
an invoice after it is read is code in factory/payables.py, never a model: the checks that decide
whether a person must look, price comparisons, account coding, export files and statement
reconciliation. A flagged document is never approved automatically; an exported one is never
changed or sent twice; a bill always adds up to its invoice total. Upgrading an operation copies
the new approved version in and switches the old deployment off, never edits a version in place.
The customer platform is served under `/portal` in the web app with its own session key
(`portal-token`) and sign-in; it shows nothing of the builder's and has no way back. Opening a
customer from Agent Factory opens a new tab and must not replace the builder's session. Scope its
styles to `.portal`. Money "worth raising" is counted conservatively in payables: same-day price
gaps only, a line counted once, and never a yearly figure from one-off findings. An invoice a statement lists that is not on file is
reported, never counted as money found. The demo for a call is documented in demo/restaurant/CALL.md:
start with demo/restaurant/start.sh, run demo/restaurant/reset.sh before every showing, and rehearse
with apps/web/tests/demo/rehearse.mjs. The reset edits the local database directly; the product has
no way to un-send an invoice and must not gain one.

Invariants: tenant ownership is checked server-side on every resource access;
immutable versions; evaluations use isolated state; production writes require
explicit authorization; secrets never enter model context or browser responses;
generated code runs only in the sandbox, holds no secrets or network, reaches systems
only through brokered capabilities and is pinned by hash in an immutable version;
promotion requires measured regression-safe evidence.
Demo mode is explicitly labeled and never represented as live model execution.
Tests must exercise behavior and security boundaries, not invented score overrides.

Continue from PLANS.md and docs/PROGRESS.md. Update both after verified milestones.
Do not declare phases complete without executing their checks. Document unavailable
external credentials and independently continue local functionality.
