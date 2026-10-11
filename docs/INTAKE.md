# Build inputs

A build is given three things: the task, business context, and a source of truth. This
document covers the last two. Code: `apps/api/factory/intake.py`. Tests:
`apps/api/tests/test_intake.py` and `apps/web/tests/e2e/intake.spec.ts`.

## The rule

A build cannot start with nothing to judge it. `truth_source(db, agent)` returns:

- `cases`: the agent's suite has development cases and held-out validation cases. This is
  the normal state after a dataset is attached, and the built-in templates have it from their
  fixtures.
- `rules`: someone stated, in `no_data_reason`, why the task can be checked without example
  data. The build then drafts cases from the rules and every one still waits for a person to
  accept it. The statement is recorded in the audit trail.
- `None`: the build is refused, by the API (422) and again in `new_job`.

A demo-mode workspace also refuses to build an agent with no tools, because demo mode replays
a fixture tool and such an agent has nothing to run on.

## Datasets

`POST /agents/{id}/datasets` takes a name and either `content` or a public `url`, an optional
column `mapping`, and the sizes of the development, regression and validation parts.

1. **Fetch.** An address is downloaded over the pinned transport: https, default port, no
   credentials, 5 MB, UTF-8 text. Each redirect is validated and pinned again, as research
   fetches are.
2. **Parse.** CSV, TSV, JSON (a list of objects, or a `rows`/`data` wrapper) and JSON Lines.
   One scalar per column. Anything unclear is refused with a message that says what to change.
3. **Map.** Columns named `expected_<field>` are the answers, which is how a file gives more than
   one answer field. Otherwise the answer column is found by name (`label`, `category`, `intent`, ...) or, with
   two columns, as the one that repeats. If it is not clear the request is refused and the
   caller names it. A single input column becomes the field `text`.
4. **Clean.** Rows with no answer or no input are left out; duplicates collapse to one; rows
   that give the same input two different answers are all left out. Each is counted.
5. **Split.** In code, not by a model. The order depends only on a seed and each row's
   content, answers are interleaved so a small sample covers as many as it can, and sizes are
   exact. A row already in the suite is never imported again, so a held-back row cannot come
   back as a development row. There are three parts: rows the builder reads (`development`),
   rows each change is scored on that it never reads (`selection`, by default as many again),
   and rows held back for the final result (`validation`). There are no regression cases by
   default: those are the ones that must never break again, and they come from real incidents.
6. **Pin the shape.** The agent's input and output schemas are derived from the data and saved
   as a new version. A text answer that repeats becomes a fixed vocabulary (`enum`), taken from
   every usable row. The architect cannot change these two schemas afterwards.

Each row becomes an evaluation case with `source = "dataset"` and one `equals` assertion per
answer field. The dataset row keeps the mapping, the counts and five development rows as a
profile. Data cannot change while a build is running. An administrator can remove a dataset
(`DELETE /datasets/{id}`): its cases go, and so do the results measured on them, so earlier
versions must be evaluated again before they can be approved.

What the builder sees: the profile (field names, the vocabulary, five development rows), and
development cases through the existing evidence and investigator tools. Held-out rows are never
in a profile, payload, tool reply or example; `test_intake.py` asserts this on a whole build.

## Business context

`POST /agents/{id}/context` stores a text document (up to 200,000 characters, 20 per agent).
Known tenant credentials are removed before it is stored and again at every boundary.

- The architect and the test designer receive the documents in their request, whole if they
  fit a 40,000 character budget and otherwise the opening of each, marked as truncated.
- The optimizer receives the same within 20,000 characters, and with investigator turns it has
  `list_context` and `read_context`, which page through the full text of this agent's
  documents only.
- The deployed agent never receives them. It gets what the builder writes into its
  instructions.
- With research enabled, the documents' contents are added to the outbound screen, so their
  text cannot leave in a question, query or URL.

Text and PDF are accepted. The browser sends a PDF to `POST /documents/text`, which returns its
text and stores nothing, and the text is then added like any other document. Word files must be
converted first.

## PDF documents

An agent is sent text. A PDF is turned into text once, at the boundary, by `factory/documents.py`
(`pdf_text`): the text layer of each page in order, with the page layout kept so that table
columns stay in line. Limits: 5 MB, 30 pages, 60,000 characters as a request field (200,000 as a
context document). Password-protected and unreadable files are refused by name.

A page with no text layer is a scan or a photo. So is a page whose only text is a line or two
laid over a page-sized image, as a court or a scanner stamps on. Such a page is never passed on
as an empty document. What happens to it depends on `DOCUMENT_READING`:

- **Off (the default).** The file is refused, naming the file and the page.
- **On.** `factory/reading.py` draws the page as an image, sends it to the model
  (`READER_MODEL`, else `OPENAI_MODEL`) and takes back a transcription. JPEG and PNG photos are
  read the same way. A typed page in the same file is still taken from its text layer.

A page scanned sideways or upside down comes back mostly marked illegible, or abandoned after a
few words. Such a page is drawn again turned a quarter each way and then upside down, each turn
one more accounted request, and the turn that reads best is the page from then on: what is read,
kept and shown. A page that reads as it lies is asked about once. This works for the pages of a
PDF; a photo sent as an image file is read as it is.

Reading is a model call and is accounted for as one. Before a page is sent, a `document_reader`
usage record is committed with a reservation; the reply settles it; a call with no reply keeps
its reservation as uncertain and is not retried. Each upload has a ceiling
(`READING_MAX_COST`, or `reading_max_cost` on the archive upload) checked before every page.
The text read from a page is kept per tenant under a hash of the image, the model and the
instructions, so a page is paid for once: an upload that stops at its limit or on a provider
failure is simply sent again and continues. Every upload that read pages writes a
`documents_read` audit event with the page count and cost, whether or not it succeeded.

What to know before turning it on: a page costs a few cents and takes ten to thirty seconds on
a large model, so a zip of several hundred scanned pages is a request of many minutes. The
transcription is a model's reading and can be wrong on dense, faint or sideways pages. The page
image reaches the provider as it is: a credential printed on a scanned page cannot be filtered
out of a picture, although the text that comes back is filtered like any other.

Examples whose requests are documents go up as a zip to `POST /agents/{id}/datasets/archive`
(multipart: `file`, `name` and the split sizes). The zip holds exactly one examples file and the
PDFs. A cell that names a PDF in the archive, by path or by file name, is replaced with that
document's text; an empty cell stays empty. One row can therefore hold a packet of documents, for
example an invoice, its purchase order and its delivery note, with the correct answer in
`expected_` columns. After that the rows are an ordinary dataset: the same mapping, cleaning,
split and pinned shape. Limits: 25 MB packed, 100 MB unpacked, 6,000 files; declared sizes are
checked before anything is unpacked and every read is bounded again.

No PDF byte and no file name is stored in a case. The same reader serves production: a caller
sends each PDF to `POST /documents/text` and puts the returned text in the request field.
`demo/restaurant/` is a worked example on public documents.

## Agents without tools

A custom agent with no connection is allowed: it works from its input alone. Its baseline
instructions name the task, the runtime offers it no tools, and `tool_correctness` is graded
only for agents that were offered tools (`tools_offered` in the run metrics). An agent with a
connection that offers no tools is still an error.

## How a build runs on this data

See `docs/RUNNING_BUILDS.md`: how changes are scored on rows the builder never reads, what
happens when the provider cannot be reached, parallel scoring, pricing, budgets and the end
states.

## Running a whole build from the command line

```bash
cd apps/api
EXECUTION_MODE=live .venv/bin/python -m benchmarks.task_build \
  --task "Route each customer message to the right banking support queue." \
  --data https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv \
  --development 150 --selection 100 --validation 100 --max-cost 40 --baseline
```

It uses the real API endpoints and the real worker loop on a temporary database, and prints
each round's development score, the held-out score of the final and (with `--baseline`) the
first version, and token spend by role.

## Not built

- Reading examples from a customer's database or other connection.
- Reading as a background job with progress. It runs inside the upload request.
- A second, independent reading of each page to catch a misread digit.
- Reading spend on a page of its own; it is in the usage ledger and the audit log only.
- Word and spreadsheet files.
- A PDF attached directly to a production request: the caller converts it with `/documents/text` first.
- A model-proposed column mapping. The guess is a fixed rule; anything unclear is asked.
- Graded answers other than exact match (free text needs a rubric, which exists per case but
  is not generated from data).
