# Operations demo: the whole platform, with an agent for each kind of paperwork

A customer workspace for a restaurant group that does not exist, Harbor Table Group, showing every
operations area the customer platform has a page for, each filled by an agent built in Agent Factory.

| Agent | Reads | Fills | Held-back score | Build cost |
|---|---|---|---|---|
| Daily sales | End-of-day till reports | Sales | 10 of 10 | $0.016 |
| Cash-up and banking | Daily cash-up sheets | Cash and banking | 10 of 10 | $0.013 |
| Delivery payouts | Platform payout statements | Delivery platforms | 10 of 10 | $0.009 |
| Timesheets | Weekly timesheet summaries | Labour | 10 of 10 | $0.021 |
| Stock counts | Weekly stock count sheets | Stock and food cost | 10 of 10 | $0.010 |
| Catering quotes | Enquiry emails | Catering and events | 10 of 10 | $0.008 |
| Licences and certificates | Licences and certificates | Compliance and upkeep | 10 of 10 | $0.012 |

Purchasing has no agent in this workspace: its page runs on generated records. The supplier-invoice
agent is shown on real invoices in `demo/restaurant/`. Profit and loss has no documents of its own.

    bash demo/restaurant/start.sh      # the app, on the live model
    bash demo/operations/build.sh      # documents, agents, workspace: everything, from nothing
    bash demo/operations/reset.sh      # back to the starting state before each showing

Sign in at http://localhost:3000/portal with username `demo` and password `demo`.
The seed script creates this account only in development; resets keep its sign-in working.

`build.sh` draws the documents, builds each agent on 24 examples (8 for the builder, 6 to score
changes, 10 held back), approves and deploys the ones that meet their target, installs them, and
sends the last week's 81 documents through them. It carries on where it left off. `CALL.md` is the
script for showing it; `apps/web/tests/demo/rehearse-operations.mjs` walks it in a browser.

## How it fits together

- `sample.py` generates eight weeks of records for the group. `documents.split` leaves the last
  week's sales, cash, payouts, labour and stock counts, every certificate and the unanswered quotes
  **out** of that history. Those reach the workspace only through an agent reading a document.
- `documents.py` draws the documents as typed PDFs in varied layouts, with the answer for each.
- An agent reads a document into a few fields. `apps/api/factory/recording.py` checks the answer
  and writes it into `portal_records`; `apps/api/factory/operations.py` works every page out from
  those. A quote's price, a till that is short, a commission above the agreed rate: all code.
- Percentages are worked out only where the paperwork exists: food cost over the weeks that have a
  stock count, labour over the days a timesheet covers. A day or week with nothing for a location
  that was plainly trading is reported as paperwork that has not arrived.
- A document the checks doubt (a figure that does not add up, a place or dish the workspace does not
  know, a second copy) is held for a person and writes nothing until one approves it.

## What is real and what is not

- **The agents are real.** Each was built by Agent Factory from examples, measured on examples it
  never saw, and runs on a live model when a document is uploaded.
- **Their documents are invented.** The group, its suppliers, platforms and customers do not exist,
  no real company is named, and every page keeps a "Sample data" mark.
- **The scores flatter the agents.** The held-back examples are drawn by the same generator as the
  ones the agents were built on: clean, typed, a handful of layouts. Ten of ten here says the agent
  works on documents like these. It says nothing about a real business's scans, handwriting or
  formats nobody anticipated. On the 81 documents the workspace was filled from, 80 were read
  exactly; one certificate's holder was read as "Prep cook" where the page says "Line cook", and no
  check could catch that.
- **Things were made to go wrong on purpose**, listed at the top of `sample.py`, so the rules have
  something to find. They are not marked in the data.
- **Seven weeks of history are generated**, not read by any agent. Only the last week came through
  documents.
