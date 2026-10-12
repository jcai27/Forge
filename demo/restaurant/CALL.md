# The call: showing the invoice demo to a prospect

Fifteen minutes on a screen share. The audience keys supplier invoices by hand today: a restaurant
bookkeeping firm, or the controller of a group of 5 to 30 locations.

**The point to land:** a bad scan goes in, every line comes out entered and checked, and only the
exceptions wait for a person. This is the job done, not money found. On this data the checks turned
up about $70 worth raising in $48,000 of invoices; do not present that as a saving.

## Before the call

    bash demo/restaurant/start.sh        # leave running; wait for http://localhost:3000/portal
    bash demo/restaurant/reset.sh        # prints the customer login

- Run the reset before every call. A showing approves and exports invoices; the reset undoes it.
- Open http://localhost:3000/portal in a clean browser window and sign in, so the first thing they
  see is the dashboard, not a password field.
- Have `demo/restaurant/data/live/` open in a file window. It holds the three invoices to upload.
- Optional dry run: `cd apps/web && node tests/demo/rehearse.mjs`, then reset again.
- Close Agent Factory tabs. The prospect should see the customer platform only.

## Ask first (2 minutes)

"How do supplier invoices get into your books today? Every line, or just the total? How many a
month, and who keys them?" Their answers tell you whether to go on, and what the work costs them.

## The path

| # | Click | Say |
|---|---|---|
| 1 | Dashboard | "This is a real restaurant group: nine locations, three weeks of Gordon Food Service invoices from a public court filing. Nothing on these pages has been changed. Every figure here was built from invoice lines nobody typed." |
| 2 | Supplier invoices, then `GFS invoice 820141051.pdf`; click the page to enlarge | "The scan as it arrived, and what was read from it: supplier, location, number, date, total, tax, and every line." Then open a long one (131958417, three pages) to show it is not only short ones. |
| 3 | Back; **Needs a person**; open the one there | "Here is what happens when it gets something wrong. The page says one case of pollock at $71.40. It was read as four at $17.85. The line still added up, so arithmetic did not catch it. The price check did: $17.85 against $71.40 last time. It was held and nobody approved it." Click **Correct**, set line 58 to quantity 1 and price 71.40, **Save and approve**. |
| 4 | Supplier invoices, **Upload documents**, pick `GFS invoice 132029719.pdf` | "This one it has never seen." It takes about 20 seconds. Talk through what is happening: the page is read, the lines entered, the checks run. When it lands, open it. |
| 5 | **Approve the N ready**; **Books**; **Send N and download** | "Clean invoices can be approved in one go, or automatically. Then they go to the books as a file in Xero's or QuickBooks' import layout, coded to your ledger accounts. Each invoice is sent once." Open the file. |
| 6 | Supplier statements; open the statement | "The supplier's own statement, checked against what is on file. Sixty invoices listed; it shows which agree, and two that are not on file here." (Those two are the other invoices in `data/live/`, which have not been uploaded. Say so if asked: "we have not sent those two in yet".) |
| 7 | Supplier invoices, **Results**, then **Prices** | "What it added up to, and every price that moved. On clean invoices like these it finds little, and it says so." |

Close with the offer: "Send me fifty of your own invoices. I will return them entered line by line,
with a report of how they compared with what you keyed."

## What the numbers are

- **58 invoices at the start, 1,241 lines.** Real, from In re Gas City, Ltd. (Bankr. N.D. Ill.
  10-47879, document 427). Three more are kept back to upload live.
- **One held for a person.** A real misreading by the agent, caught by the price check. Nothing
  was planted.
- **Hours saved (Results).** The invoice count times minutes and a wage the viewer types in. The
  5 minutes and $20 shown are placeholders. Ask them for theirs and type it in.
- **Worth taking up with suppliers: about $70.** Price rises against the last price paid, and three
  times one location paid more than another on the same day. Small, and honest.
- **Live upload timings, measured cold:** 132029719 (1 page, 6 lines) 22 s; 821095277 (1 page,
  8 lines) 16 s; 132011648 (2 pages, 21 lines) 23 to 24 s. All three came out right against the
  answer key on every field and line.

## Questions to expect

**How accurate is it?** On 28 real invoices held back from the build, 21 came out right in every
field and every line, and 98.4% of the individual checks passed. In this customer's 61 invoices,
one line in 1,276 was caught as misread; the number, date, total and tax of all 60 that have an
answer key matched it. Line items of the invoices here were not all checked by hand, so do not
claim more than that. The honest answer for their invoices: "I do not know until I run yours, which
is why I am asking for fifty."

**What happens when it is wrong?** Step 3. The checks are code, not a model: lines must add up to
the total with tax, a price far from the last one paid is held, a repeated invoice number is held,
an unreadable field is held. What they cannot catch is a misreading that still adds up and is
close to the last price.

**Does it load into QuickBooks or Xero?** The files follow each product's published bill-import
layout. They have **not** been imported into a live account of either; say exactly that. There is
no direct connection, only the file and a webhook.

**Where do our documents go?** Pages are sent to OpenAI's API to be read, and the pages and
results are kept in the application's database, each customer in a workspace of its own. Today
that is a laptop. There is no hosted service, no security certification and no uptime commitment
yet. Do not imply otherwise.

**Can it read our suppliers?** It was built and measured on three suppliers (Gordon Food Service
and two produce houses). Some sideways Sysco pages read poorly before a page-turning fix and have
not been measured since. Their suppliers are untested.

**Email?** A mailbox can be connected (Channels) and is checked every two minutes. It has been
tested against a stand-in mail server, not a real Gmail or Outlook account. Do not demonstrate it.

**What does it cost?** No price is set. Decide yours before the call. Reading these invoices cost
well under a cent each in model fees, so the price is about your time and their value, not cost.

## If something goes wrong

- **The upload sits for more than a minute.** Keep talking over step 6 in another tab; the read
  continues. If it ends "could not be read", upload it again: a page already read is not paid for
  twice. If the provider is down, say so and open one of the invoices already there instead.
- **A read comes out wrong live.** That is step 3 happening for real. Show the check that caught
  it, or correct it on the page. Do not hide it.
- **A page shows an error.** Reload. If it persists, stop sharing, restart `start.sh`, and carry on
  from the dashboard. Nothing is lost by a restart.
- **You already approved or exported everything.** That is a showing left un-reset. Run
  `reset.sh` and reload.

## Known limits

- Runs on this machine only. One customer session per browser.
- One supplier in the customer's workspace, three weeks of invoices, no purchase orders, delivery
  notes or stock counts. The dashboard shows goods invoiced, not stock on hand.
- No product categories. Quantity mixes cases and pieces; meat sold by weight counts as one case.
- Export files unverified against live accounting systems. Mailbox unverified against a real one.
- The statement agent was built on statements drawn from real figures; one statement is real.
