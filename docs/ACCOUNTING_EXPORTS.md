# Sending approved invoices to Xero and QuickBooks Online

Approved invoices leave the customer platform as a CSV file in the layout each accounting system
imports as bills (Books > Send to the books). This page sets those files against the vendors' own
published instructions, field by field.

**Where this stands:** the files are checked against the published specifications. They have **not**
been imported into a live Xero or QuickBooks organisation: no trial account was available. The
import steps for a free trial of each are at the end, and take a few minutes.

## QuickBooks Online

Source: Intuit, "Import your bills in QuickBooks Online"
(https://quickbooks.intuit.com/learn-support/en-global/help-article/import-transactions/import-bills-quickbooks-online/L4Q6QWsRw_ROW_en)
and "Common questions about importing data to QuickBooks Online"
(https://quickbooks.intuit.com/learn-support/en-us/help-article/import-export-data-files/common-questions-importing-data-quickbooks-online/L4OYJRFdj_US_en_US),
read October 2026.

| Intuit says | The file | |
|---|---|---|
| Mandatory columns: Bill no., Supplier, Bill Date, Due Date, Account, Line Amount, Line Tax Code | Those seven headings, and Line Description | matches; the heading was "Bill No." and is now "Bill no." |
| A bill with several lines repeats the bill number, supplier and bill date on each | Every line carries them | matches |
| "No more than 100 bills are imported at one time" | At most 100 bills a file; the rest stay approved for the next | matches |
| "You can only import spreadsheets with less than 1,000 rows" | **Was not respected**: 100 bills of 21 lines is 2,100 rows. A file now stops before 1,000 rows as well | fixed |
| "Total bill amount should be 0 or greater"; no credit notes | **Was not checked.** A bill below zero now stops the export, named, before a file is made | fixed |
| You choose the date format while importing (D/M/YYYY is the example) | **Was always YYYY-MM-DD.** Dates are now written month first, day first or year first, as the customer sets | fixed |
| Line accounts must already exist in QuickBooks | The Account column holds the customer's own ledger codes | the customer's to get right; said on the page |
| Suppliers must exist, or tick the box to create them on import | Supplier name as read from the invoice | tick the box on first import |
| Line Tax Code is mandatory when tax is turned on; codes are matched during import | Written from the customer's tax setting, blank if none | blank will be refused where tax is on |
| The invoice's own tax | A line of its own, so the bill adds up to the invoice total | by design: tax is not computed twice |

**Who can use it.** Intuit: "Importing Bills is restricted to QuickBooks Online Advanced and higher
subscription tiers in the US region"; other US tiers are pointed to "Upload multiple bills" on the
Bills page, which reads bill documents, not this file. The global article describes the import for
Essentials, Plus and Advanced outside the US. So for a US customer on Simple Start, Essentials or
Plus **this file is no use**, and that is most small restaurants. Ask which plan before promising it.

## Xero

Source: Xero Central, "Import bills and credit notes"
(https://central.xero.com/s/article/Import-bills-and-credit-notes-US). That page loads its text
with a script and could not be read here beyond what search results quote of it: you download
Xero's CSV template, fill it in and import it, and imported bills arrive as drafts. The column
rules below are therefore from the template as widely documented, **not confirmed against Xero's
own page**. Download the template from your own organisation and compare the headings before the
first import: `head -1` of the file should hold every starred heading of the template.

| The template, as documented | The file | |
|---|---|---|
| Required: *ContactName, *InvoiceNumber, *InvoiceDate, *DueDate, *Description, *Quantity, *UnitAmount, *AccountCode, *TaxType | Exactly those nine headings | matches |
| *TaxType must be the name of a tax rate in the organisation | **Was written blank when no tax setting was made.** An export to Xero is now refused until one is set | fixed |
| Dates as the organisation's region writes them | **Was always YYYY-MM-DD.** Now as the customer sets | fixed |
| *AccountCode must exist in the chart of accounts | The customer's own ledger codes | the customer's to get right |
| UnitAmount is before tax | Unit price as on the invoice; the invoice's tax is a line of its own | check against how the organisation treats tax on purchases |
| The template's other columns (address, Total, InventoryItemCode, TaxAmount, tracking, Currency) are optional | Left out | not confirmed that a file without them imports |

## Trying it in a free trial

Both vendors offer a trial with a demo company. Nothing below can be done for you: each needs an
account in your name.

**QuickBooks Online** (a US trial must be Advanced, see above)
1. Start a trial at https://quickbooks.intuit.com and open the sample or a new company.
2. Settings > Chart of accounts: make sure accounts with the codes you set under Books exist.
3. Settings > Account and settings > Sales > turn on Custom transaction numbers.
4. In the customer platform: Books > set the tax code and date format > approve a few invoices >
   Send to the books as QuickBooks.
5. Settings > Import data > Bills > choose the file > tick the box to add new suppliers > pick the
   date format the file uses > map the columns (they should map themselves) > map tax codes >
   Start import.
6. Expenses > Bills: open one and check supplier, dates, account, lines and total against the
   invoice.

**Xero**
1. Start a trial at https://www.xero.com and use the Demo Company.
2. Accounting > Chart of accounts: note the codes; Accounting > Advanced > Tax rates: note the exact
   name of the rate for untaxed purchases.
3. In the customer platform: Books > set those account codes, that tax type and the date format >
   approve a few invoices > Send to the books as Xero.
4. Business > Bills to pay > Import > download the template and compare its headings with the
   file's first line > Browse > the file > Import.
5. The bills arrive as drafts. Open one and check it against the invoice, then approve it.

Tell me what either import reports and the file is fixed against the real thing.
