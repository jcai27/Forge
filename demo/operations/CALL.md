# The call: showing the whole platform

About fifteen minutes on a screen share, for the controller of a restaurant group or a bookkeeping
firm. Show `demo/restaurant/CALL.md` first if you have time: that one is real invoices.

**Say this at the start, and mean it:** "This is a made-up restaurant group. The agents are real
and you will watch them read documents, but the documents were generated for this demo. I am
showing you what the platform does across a business, not somebody's results."

## Before the call

    bash demo/restaurant/start.sh        # leave running
    bash demo/operations/reset.sh        # before every showing

- Sign in at http://localhost:3000/portal as `harbor@demo.test` / `harbortable`.
- Have `demo/operations/data/live/` open in a file window: two documents for each agent.
- Optional dry run: `cd apps/web && node tests/demo/rehearse-operations.mjs`, then reset again.

## The path

| # | Click | Say |
|---|---|---|
| 1 | Dashboard | "Four locations, eight weeks. Sales, food cost, labour and profit, and under them everything the rules found across the business, each with a link to where it came from." |
| 2 | Agents | "One agent for each kind of paperwork. Each was built from examples and measured before it was allowed near a customer." |
| 3 | Daily sales, **Upload documents**, `live/till/Till report Dockside 2026-09-27.pdf` | Point first at the dashboard's "Dockside: no till report has arrived for Sep 27". "It knows what it is waiting for. Here is that report." About five seconds. Open it: the page beside what was read. Then Sales: Sunday is there, and the warning is gone. |
| 4 | Delivery payouts, upload `live/payout/Plate Runner payout Downtown 2026-09-21.pdf`, then Delivery platforms | "It read the statement. Code then checked it against the rate you agreed. Further down: four earlier weeks where this platform took 28% against an agreed 25%, $660." |
| 5 | Catering quotes, upload `live/enquiry/Enquiry Castellan Brewing.pdf`, open it | "An enquiry email. The agent read who, when, how many and which menu. The price is arithmetic over your menu: portions, 10% off for the size, six servers. The agent never chooses a price." |
| 6 | Licences and certificates, upload `live/certificate/Renewed kitchen hood cleaning certificate Dockside.pdf`, then Compliance and upkeep | "Dockside's hood cleaning certificate had lapsed. This is the renewal. The expired one is gone from the list." |
| 7 | Stock and food cost | "Dockside uses about 2.5 points more food than its sales explain, most of it seafood, and the waste sheets account for little of it. Nobody typed that; it falls out of the counts and the tills." |
| 8 | Profit and loss | "And because every page is worked out from the same documents, this is too. Nothing is entered twice." |

If they want to see a document held: upload `held/till/Till report Downtown 2026-09-27 misprinted.pdf`
to Daily sales. Its delivery figure is $300 too high, so the channels no longer add up to net sales.
It waits under "Needs a person" with the reason, and nothing is recorded until someone corrects it.

## Questions to expect

**Are these real agents?** Yes: built in Agent Factory, measured on held-back examples, running on a
live model as you watch. **Is this real data?** No, and say so.

**How accurate?** Each scored ten of ten on held-back examples, and 80 of the 81 starting documents
were read exactly. But the examples are clean generated PDFs in a handful of layouts, so that is an
easy test. It says the pipeline works. It does not say how they would do on your documents, which
is what a pilot is for.

**What happens when one is wrong?** Checks in code hold a document whose figures do not add up,
that names a place, dish or platform you do not have, or that has arrived before. What they cannot
catch is a plausible misreading: one certificate here has the wrong job title recorded.

**Which of this exists for real documents today?** Supplier invoices and statements
(`demo/restaurant/`). Everything on this workspace would need building again on a real customer's
own documents, and measuring there.

**What about purchasing?** Its page in this workspace runs on generated records; no agent fills it
here.

**Does it connect to our till, payroll or bank?** No. It reads documents. There are no direct
connections to any system.

## If something goes wrong

- **An upload fails or is held unexpectedly.** Open it and read the reason aloud; that is the checks
  working. Then use the other document in the same `live/` folder.
- **A page shows an error.** Reload. If it persists, restart `start.sh` and carry on.
- **Numbers look odd before you start.** A showing was left un-reset. Run `reset.sh`.

## Known limits

- Runs on this machine only. Documents are typed PDFs, not scans or photos.
- Seven of the eight weeks are generated history; only the last week came through agents.
- Eight documents are missing at the start on purpose (the ones in `live/`), and the pages say so.
  Until they are uploaded, profit is overstated by their costs; the Profit and loss page says that too.
- Purchasing and waste have no agent here. Bank statements are not read: the cash-up sheet carries
  what was banked and settled.
- The quoting agent prices three fixed packages. It does not send the quote or follow it up.
- Nothing here connects to another system, sends an email or takes a payment.
