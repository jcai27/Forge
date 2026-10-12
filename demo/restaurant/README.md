# Restaurant demo: real supplier invoices

Real invoices from food suppliers, as scans, read by an agent and then checked, approved and sent
to the books in a customer's own workspace. See docs/CUSTOMERS.md for the customer side and
docs/INTAKE.md for how scans are read.

## What the data is

When a food distributor sues over unpaid bills, or claims in a bankruptcy, it files the invoices
as exhibits. Federal court filings are public, and the RECAP archive (courtlistener.com) serves
them free. This set is three such exhibits, unchanged:

| Supplier | Customer | Invoices | Dates | Court record |
|---|---|---|---|---|
| Gordon Food Service | A group of Indiana diners and truck stops, 10 locations | 60 | October 2010 | In re Gas City, Ltd., Bankr. N.D. Ill. 10-47879, doc. 427 |
| W.R. Vernon Produce | A produce reseller | 34 | Aug 2015 to Feb 2016 | M.D.N.C., RECAP docket 71157, doc. 5-2 |
| Gramercy Produce | A New York restaurant group | 9 | Nov to Dec 2017 | S.D.N.Y., RECAP docket 496593, doc. 1-1 |

103 invoices on scanned pages. The exhibits themselves are not in the repository; `prepare.py`
downloads them into `source/` and builds everything under `data/` from them and `labels.json`.

| File | What it is |
|---|---|
| `labels.json` | Every invoice's header, tax and line items: the answer key |
| `statement-key.json` | The rows of the one real supplier statement (Gordon Food Service's own summary of its invoices) |
| `data/invoice-desk-procedure.md` | The rules the invoice agent is built to follow. Read by the builder only |
| `data/statement-procedure.md` | The same for the statement agent. Written by `statements.py` |

## Where the answers come from

Nothing was planted. A model read each page image into line items. An invoice was kept only if
every line's quantity times unit price equals its amount, by weight for items sold by the pound,
and the lines and tax add up to the printed total. For Gordon Food Service the number, date and
total also had to match the supplier's own summary, filed in the same exhibit. The numbers and
dates on the two produce suppliers' invoices were then checked by eye against the page images,
and eight were corrected.

Say this plainly in a pitch:

- Invoices that failed those checks were left out, so the set leans towards pages that read cleanly.
- The line items were read by a model. The arithmetic makes a wrong digit unlikely, not impossible.
- The procedures and the 5% price rule are ours, written for this demonstration.
- These are real businesses' records. Show them as public court filings and do not alter them.
- There are no purchase orders or delivery records, so nothing is checked against what was ordered.
- The statement examples the statement agent is built on are drawn from the real invoice figures;
  only one statement is real.

## What the agents do

- **Invoices.** From the text of a scanned invoice: supplier, customer, invoice number, date,
  total, tax, and every line with its item code, description, quantity, unit price and amount.
- **Statements.** From a supplier's statement: the supplier, and each invoice it lists with its
  number, date and amount.

Price rises, whether lines add up, duplicates, account coding and statement reconciliation are
worked out in code on the customer side (`apps/api/factory/payables.py`), not by an agent.

## Running it

The app must run on a live model that reads images, with `DOCUMENT_READING=true`. Reading,
building and processing all spend money on the model provider. From `apps/api`:

    uv run python ../../demo/restaurant/prepare.py                    # download exhibits, build data/
    uv run --with reportlab python ../../demo/restaurant/statements.py # draw the statement examples
    uv run python ../../demo/restaurant/setup.py                      # build the invoice agent
    uv run python ../../demo/restaurant/setup.py --statements         # build the statement agent

Approve and deploy each agent from its build page. Then:

    uv run python ../../demo/restaurant/run_batch.py INVOICE_AGENT_ID
    uv run python ../../demo/restaurant/customer.py INVOICE_AGENT_ID --statements STATEMENT_AGENT_ID

## Showing it

    bash demo/restaurant/start.sh     # the app, with agents and page reading on the live model
    bash demo/restaurant/reset.sh     # the customer back to its starting state; prints the login

`start.sh` is `scripts/dev.sh` with `live.env` laid over `.env`. `reset.sh` undoes a showing in the
local database without reading a page again, takes the three invoices kept for uploading live back
out (they are written to `data/live/`), and keeps the customer login in `.login`. CALL.md is the
script for a call. To rehearse it in a browser, with the app running:

    bash demo/restaurant/reset.sh && (cd apps/web && node tests/demo/rehearse.mjs)

`run_batch.py` runs the held-back week through the deployed agent on the builder's side and writes
`data/batch-report.html`. `customer.py` opens a customer workspace, installs both agents, sends the
Gordon Food Service invoices through the portal in date order, except the three kept back to
upload in front of someone, reconciles the real statement
and prints a local login for the customer. `prepare.py --examples 30 --batch 8` builds a smaller set.

Measured results are in docs/PROGRESS.md.
