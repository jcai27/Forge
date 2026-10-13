# Operations demo: the whole platform, on sample data

A customer workspace for a restaurant group that does not exist, Harbor Table Group, showing every
operations area the customer platform has a page for:

| Area | What the page works out | An agent would fill it from |
|---|---|---|
| Dashboard | Sales, food cost, labour, operating profit, and everything any area's rules found | All of the below |
| Sales | By day, location, channel and service; average check; what sold and its margin | The till's end-of-day reports |
| Purchasing | Spend by supplier and category, credits asked for and not received, prices that changed | Supplier invoices, credit notes, statements |
| Stock and food cost | Stock used against what the recipes say, by location and category; waste | Stock count sheets, waste sheets |
| Labour | Cost as a share of sales, sales per hour, overtime, hours over the rota | Timesheets and rotas |
| Cash and banking | Tills that did not balance, cash not at the bank, card settlements that came in short | Cash-up sheets, bank and card statements |
| Delivery platforms | Commission against the agreed rate, payouts against their own arithmetic | Platform payout statements |
| Catering and events | Quotes won, what customers owe, events coming up without a deposit | Quotes, event orders, customer invoices |
| Profit and loss | By location, from the figures of the other areas | Nothing of its own |
| Compliance and upkeep | Licences expiring, temperature checks missing, repairs waiting | Certificates, logs, repair tickets |

    bash demo/restaurant/start.sh      # the app (any mode; these pages call no model)
    bash demo/operations/seed.sh       # open the workspace, fill it, print the login

Then sign in at http://localhost:3000/portal, or open Harbor Table Group from Customers in Agent Factory.

## What is real and what is not

- **The pages and the arithmetic are real.** Every figure is worked out in `apps/api/factory/operations.py`
  from stored records, and what "needs attention" is decided by rules written there.
- **The data is not.** `sample.py` generates it. The group, its suppliers, delivery platforms and
  customers are invented, and no real company is named. Every page says so, and the workspace
  carries a "Sample data" mark.
- **No agent fills these pages yet.** Only supplier invoices and statements have agents, shown on
  real documents in `demo/restaurant/`. Each other area would need its own agent built and
  measured on that area's real documents.
- **Things were made to go wrong on purpose**, listed at the top of `sample.py`, so the rules have
  something to find. They are not marked in the data; the rules find them.

Say this when showing it: it is what the platform would look like across a business, not a record
of one. Steel City Diners in `demo/restaurant/` is the part that runs on real documents today.
