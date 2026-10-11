# Invoice desk procedure

How supplier invoices are recorded when they arrive. Written for this demonstration; it is not a
document from any of the businesses whose invoices appear in the examples.

Every invoice is recorded in full: the header, and every line.

## The header

- **supplier**: one of our supplier names, exactly: `Gordon Food Service`, `W.R. Vernon Produce`,
  `Gramercy Produce`.
- **customer**: the location the goods went to, as the invoice names it under ship-to or sold-to.
  Not the bill-to company and not the account number.
- **invoice_number**: as the supplier prints it, digits only, keeping any leading zero. A court
  filing stamp across the top of a scan ("Case ... Doc ... Page 3 of 22") is not part of the invoice.
- **invoice_date**: the invoice date, as YYYY-MM-DD. Not the order date, ship date or filing date.
- **total_cents**: the invoice total, tax included, in cents. $2,533.11 is 253311. On an invoice of
  several pages the total is printed on the last page only.

- **tax_cents**: the tax charged on the invoice, in cents, as printed in its tax box or tax line.
  0 when the invoice charges none. The lines and the tax together make the total.

## The lines

**items** has one row for every line that carries an amount, in the order printed, across all pages
of the invoice. That includes freight, fees and deposits charged as lines. It does not include a
sub-line that only restates a weight ("ITEM 192340 = 12.47 LB / $98.89"), subtotals, category
summaries or page totals.

Each row records:

- **code**: the supplier's item code. Gordon Food Service prints one on every line. The produce
  suppliers print none, and their rows have no code: the country of origin in their first column
  is not a code.
- **description**: as printed.
- **quantity**: the quantity shipped. For an item sold by weight this is the number of cases, not
  the pounds.
- **unit_price**: as printed, in dollars. For an item sold by weight it is the price per pound.
- **amount**: the line's extended amount, in dollars.
