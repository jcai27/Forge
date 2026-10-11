# Supplier statements

How a supplier's statement is recorded. Written for this demonstration.

A statement lists the invoices a supplier says it has billed. We record it so it can be set
against the invoices we have received.

- **supplier**: one of our supplier names, exactly: `Gordon Food Service`, `W.R. Vernon Produce`,
  `Gramercy Produce`.
- **rows**: one row for every invoice the statement lists, in the order printed, across all pages.
  Not the total line, not headings, not payments or notes.
  - **invoice_number**: as printed, digits only, keeping any leading zero.
  - **invoice_date**: as YYYY-MM-DD, whatever format the statement uses.
  - **amount**: the amount for that invoice, in dollars, as a number.
