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
3. **Map.** The answer column is found by name (`label`, `category`, `intent`, ...) or, with
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

Only text is accepted. PDF and Word files must be converted first.

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
- PDF, Word and spreadsheet files.
- A model-proposed column mapping. The guess is a fixed rule; anything unclear is asked.
- Graded answers other than exact match (free text needs a rubric, which exists per case but
  is not generated from data).
