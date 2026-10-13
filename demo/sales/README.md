# Sales summaries: a second agent measured on real documents

Thirteen real point-of-sale sales summaries, and an agent built on them through Agent Factory.

## What the data is

A restaurant in Chapter 11 files a monthly operating report with the court, and this one attached
its point-of-sale system's sales summary to each. Federal filings are public; the RECAP archive
(courtlistener.com) serves them free. These are from **In re Smokecraft Clarendon, LLC, Bankr. D. Md.
24-13609**: two single days (29 and 30 April 2024) and eleven months, May 2024 to April 2025.
September 2024's is not in the archive. Nothing in them has been changed, and the filings
themselves are not in this repository: `prepare.py` downloads them.

They are typed PDFs, not scans, in three layouts: a plain export of labels and amounts; the same
export with each table on a page of its own as a row of headings over a row of amounts; and the
point-of-sale system's two-column printed report with charts.

## What the agent reads

Fourteen figures: the restaurant, the first and last day covered, gross sales, discounts, refunds,
net sales, tax, gratuity, tips collected, total guests, total orders, and the expected and actual
closeout cash.

## Where the answers come from

`label.py` reads them from each document's own text with a parser written for the three layouts,
and keeps a document only if gross sales less discounts less refunds equals net sales to the cent.
All thirteen do. Six were also checked by eye against the printed lines. The parser made the answer
key; the agent is built from examples and never sees it.

## The result

    cd apps/api
    uv run python ../../demo/sales/prepare.py    # download the filings, cut the summaries, package them
    uv run python ../../demo/sales/build.py      # build in Agent Factory, measure on the held-back ones

Five summaries for the builder to read, eight held back. On gpt-6-luna the agent read **all eight
held-back summaries right in every one of the fourteen figures** (112 of 112), in one round, for one
cent.

Read that for what it is:

- **Eight documents, one restaurant, one point-of-sale system.** It shows the agent copes with these
  three layouts. It says nothing about another system's reports.
- **Typed, not scanned.** The figures are in the PDF's text, so nothing had to be read from an image.
- **The same figures a parser could find.** That is how the answers were made. An agent is worth
  having where layouts are too many to write a parser for, and thirteen documents do not show that.
- It is not wired into the operations pages. Those take a day's till report per location; these are
  mostly a month's.

What it does add: before this, only supplier invoices and statements had been measured on documents
nobody here made.
