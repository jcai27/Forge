# The customer side

Agent Factory has two sides. The builder's side is where an agent is designed, measured and
approved. The customer's side is where that agent works: a customer's documents arrive, are
processed, and their people see the results. This document covers the second.

## Workspaces

A customer has a workspace of their own. It is an organization like any other
(`organizations.kind = "customer"`, `parent_org_id` the builder's), so their documents, page
images, runs, spend and audit history are separated from the builder's and from every other
customer's by the same tenant check as everything else. Nothing in the builder's workspace is
visible from it: not the examples an agent was built on, not its evaluations, not other
customers.

The builder opens a workspace on the Customers page (`POST /customers`) and becomes its
administrator. Removing that membership ends the builder's access to it.

## Putting an agent to work

`POST /customers/{id}/operations` installs a deployment as an **operation** in the customer's
workspace. It copies the approved version exactly, creates a deployment there with its own
spending limits, and records where it came from. The customer sees an operation by the name the
builder gives it ("Supplier invoices").

Only an active deployment of an approved version can be installed, and for now only an agent
that uses no connections or tools and takes one document as its whole request. The version was
measured in the builder's workspace; the copy carries no evaluation of its own.

Documents are processed as the member who installed the operation, who must still hold write
access in the customer's workspace, in the same way a deployment trigger runs as the person who
set it up.

## The customer role

The customer's people are invited with the role `customer` (`POST /customers/{id}/invitations`). That role reaches `/portal/*`, `/auth/*` and the
invitation acceptance endpoint, and nothing else. The check is made in `security.principal`,
where every request's membership is resolved, so no endpoint can omit it. In their own
workspace a customer cannot read the installed agent's instructions, its runs' internals, the
member list or the audit log.

An invited person joins at `/portal`: "I have an invitation code", then the invited email, a
password and the code. Behind that form an account is registered (or signed in to, if the email
has one) and the invitation accepted. Registration still gives them an empty workspace of their
own beside the customer's, which they never see; that is a rough edge, noted under Not built.

## How documents arrive

| Channel | How it works |
|---|---|
| Upload | PDF, PNG or JPEG from the inbox page. |
| Mailbox | An IMAP mailbox, checked every two minutes for PDF and image attachments. |
| Inbound address | `POST /portal/inbound/{channel}` with the channel's key as a bearer token and the file in a `file` field. For scanners, forwarding services and other systems. |

**Mailbox.** TLS on port 993 only, opened read-only. When it is connected the mailbox is opened
once to prove the details and to note its position; only mail that arrives afterwards is read,
never its history, and nothing is marked, moved or deleted. The password is encrypted at rest
and never returned. The server name is validated like any other outbound address: every address
it resolves to must be public, and the connection goes to the address that was checked, with the
certificate verified against the name (`factory/mailbox.py`). At most ten messages are read per
check; the rest wait for the next.

**Inbound address.** The key is shown once and only its hash is kept. A request with a wrong or
missing key gets a plain 404.

Each file is one document. The same file twice, by content hash, is the same document. A file
is read (`factory/reading.py`, with the reading settings the agent was built with), every page
is kept as an image, and the text goes through the operation's deployment on the ordinary
production queue, so the deployment's limits and the usage ledger apply. A failure is recorded
on the document with a reason a person can read.

## What happens to an invoice

Received, read, checked, approved, sent to the books. Each step is recorded on the document.

**Checked.** Once an agent has read an invoice, `factory/payables.py` checks it in code. No model
is asked. A document the checks find nothing wrong with is *ready*; one they flag *needs a
person*, with the reason in words:

| Check | What it catches |
|---|---|
| Lines, tax and total | The lines and the tax do not make the total: a misread figure, or a charge that is on no line |
| Line arithmetic | Quantity times unit price is not the amount (items sold by weight are checked by weight) |
| Seen before | Another document from the same supplier with the same invoice number |
| Price out of line | A unit price three times the last price paid, or a third of it: almost always a misread decimal |
| Unreadable | A header field or a line amount that could not be read, a date that is not a date |

The checks are suspicious of the reading on purpose. A price that looks misread is not reported
as a price rise and does not become the "last price paid" until a person has approved it.

**Approved.** A person approves a document, corrects it and approves it, or approves all the
ready ones at once. A correction must fit the answer's shape; the agent's own answer is kept
beside it and the checks run again on the corrected one. A customer can choose to have ready
documents approved automatically; flagged ones always wait.

**Sent to the books.** Each supplier is coded to a ledger account from the customer's own list,
with a default for the rest. Approved invoices are exported as a bills import file for Xero or
QuickBooks Online, or as plain lines. A document is sent once and marked; the file is kept so
the same batch can be fetched again. Every bill adds up to its invoice total: tax goes on a line
of its own, and an item sold by weight goes as one unit at its amount. Nothing is sent for a
supplier with no account. The column headings follow each system's published template and
should be checked against the customer's own account the first time; there is no direct
connection to either system.

**Statements.** A second kind of operation reads a supplier's statement into the invoices it
lists. Each is matched by invoice number to the invoices received: it agrees, the amount
differs, the supplier lists it and it never arrived, or it is on file and the supplier does not
list it.

**A better agent later.** `POST /customers/{id}/operations/{operation}/upgrade` puts a newer
approved version behind an operation and reads again, from the stored pages, every document no
person has approved. A page read before is not paid for again.

## What the customer sees

The customer platform is a place of its own, at `/portal`. It has its own sign-in page and its
own browser session (`portal-token`), separate from Agent Factory's (`factory-token`), and shows
nothing of the builder's: no agents under construction, no evaluations, no way back. A person
joins there with the invitation code the provider sent. From Customers, "Open customer platform"
opens it in a new tab as the customer sees it and leaves the builder signed in where they were.
A customer-workspace session that turns up at a builder address is handed to `/portal`.

- **Dashboard.** Purchasing analytics over every invoice agent in the workspace
  (`GET /portal/analytics`, worked out in `payables.analytics`): purchases, deliveries invoiced,
  cases and pieces received and different items bought; what came in by day (by week past 45
  days) in dollars or quantity; purchases by location and supplier; the items the most money
  went on or that came in in the greatest quantity, with the range of prices paid; and prices
  that moved. One location can be picked. Below it, each agent with what is waiting for a
  person. Quantity is the invoice's own line quantity, cases or pieces, not pounds. There are
  no product categories: the agent does not record one.
- **A page for each agent** (`/portal/agents/{operation}`), with tabs. An invoice agent has:
  - **Documents.** Every document by where it stands: needs a person, ready, approved, sent.
  - **Results.** How many invoices were read and lines entered, how many needed nobody, what was
    caught, what is worth raising with a supplier, and where the money went by location and
    week. Hours saved are the customer's own minutes per invoice times the count. Prints as a
    report.
  - **Prices.** Each line against the last price paid for the same item by the same location
    from the same supplier; more than 5% up is listed, with what it cost. And the same item
    invoiced to two locations on the same day at different prices.
  - **Books.** Accounts, automatic approval, and sending approved invoices on.
  - **Channels.** Connect a mailbox, create an inbound address, or have results posted on.

  A statement agent has Documents and Channels.
- **Document.** The pages beside the answer, what the checks raised, approve or correct; for a
  statement, each listed invoice set against the invoices received.

What is "worth raising" is counted conservatively. A line that is both a price rise and a
difference between locations is counted once. Only differences between locations are carried to
a yearly figure, because a rise is counted once on the invoice where it rose.

## Where results go

- **Books export.** As above.
- **Lines export.** `GET /portal/operations/{id}/export.csv`: every line of every processed
  document. Cells a spreadsheet would run as a formula are written as text.
- **Webhook.** Each approved result is posted once as JSON to an https address, through the
  pinned transport (public addresses only, no redirects), with an optional bearer key. A failed
  delivery is recorded on the document and is not retried.

## Not built

- A direct connection to an accounting system. There are import files for Xero and QuickBooks
  Online, unverified against a live account, and the webhook.
- Checking an invoice against a purchase order or a delivery record.
- Payment: due dates are written on bills, but nothing tracks what has been paid.
- Account coding per item or category; it is per supplier.
- Sign-in with Google or Microsoft for mailboxes; it is IMAP with a password or app password.
- A dedicated address per customer that mail can be forwarded to. That needs a mail domain.
- Registration for an invited customer without a workspace of their own.
- Customer-side roles (who may connect channels, who may only look), notifications, and billing.
- Installing an agent that uses connections or tools.
