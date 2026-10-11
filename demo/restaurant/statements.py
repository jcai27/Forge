"""Examples for a second agent: reading a supplier's statement into the invoices it lists.

A statement is a supplier's own list of what it has billed: invoice numbers, dates and amounts.
Set against the invoices actually received, it shows what never arrived, what the supplier has
for a different amount, and what the supplier has not listed.

There is one real statement in the court exhibits (Gordon Food Service's summary of its invoices),
and one document is nothing to build or judge an agent on. So the examples are drawn: each takes
real invoices from labels.json, for one supplier, and lays their numbers, dates and totals out as a
statement in one of several layouts. The figures are real; the pages are made here. The real
statement is kept out of the examples and used afterwards to see how the agent does on the real thing.

    cd apps/api && uv run --with reportlab python ../../demo/restaurant/statements.py

Writes data/statement-examples.zip and data/statement-procedure.md.
"""

import hashlib
import io
import json
import random
import zipfile
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent
SEED = "statements-1"
COUNT = 72
STAMP = (2010, 10, 25, 0, 0, 0)
TITLES = ("STATEMENT", "Statement of Account", "ACCOUNT SUMMARY", "Open Invoices", "Customer Statement")
NUMBER = ("Invoice No.", "Invoice #", "Invoice", "Document No.", "Reference")
DAY = ("Invoice Date", "Date", "Inv. Date", "Document Date")
AMOUNT = ("Amount", "Balance", "Open Amount", "Invoice Total", "Amount Due")
DATES = ("%m/%d/%Y", "%Y-%m-%d", "%d-%b-%y", "%m/%d/%y", "%b %d, %Y")


def draw(supplier, customer, rows, rng):
    """One statement as a PDF, and nothing else: the layout is chosen here, the figures are given."""
    order = rng.choice((("number", "day", "amount"), ("day", "number", "amount"), ("number", "amount", "day")))
    headings = {"number": rng.choice(NUMBER), "day": rng.choice(DAY), "amount": rng.choice(AMOUNT)}
    account = rng.random() < 0.5 and any(row["account"] for row in rows)
    shape, money = rng.choice(DATES), rng.choice(("${:,.2f}", "{:,.2f}", "{:.2f}"))
    font, size, step = (
        rng.choice(("Helvetica", "Courier", "Times-Roman")),
        rng.choice((9, 10, 11)),
        rng.choice((14, 16, 18)),
    )
    columns = (["account"] if account else []) + list(order)
    left = [60 + index * (480 // len(columns)) for index in range(len(columns))]
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, pagesize=letter)

    def head():
        page.setFont(
            font + ("-Bold" if font != "Times-Roman" else ""), size + 5
        ) if font != "Times-Roman" else page.setFont("Times-Bold", size + 5)
        page.drawString(60, 740, supplier)
        page.setFont(font, size)
        page.drawString(60, 722, rng.choice(TITLES))
        page.drawString(60, 706, f"To: {customer}")
        y = 676
        for x, column in zip(left, columns, strict=True):
            page.drawString(x, y, "Account No." if column == "account" else headings[column])
        return y - step

    y = head()
    for row in rows:
        if y < 70:
            page.showPage()
            y = head()
        values = {
            "account": row["account"],
            "number": row["number"],
            "day": date.fromisoformat(row["day"]).strftime(shape),
            "amount": money.format(row["amount"]),
        }
        page.setFont(font, size)
        for x, column in zip(left, columns, strict=True):
            page.drawString(x, y, values[column])
        y -= step
    if rng.random() < 0.6:
        page.drawString(left[-2] if len(left) > 1 else left[0], y - 6, "Total")
        page.drawString(left[columns.index("amount")], y - 6, money.format(sum(row["amount"] for row in rows)))
    page.save()
    return buffer.getvalue()


def main():
    invoices = json.loads((HERE / "labels.json").read_text())
    by_supplier = {}
    for invoice in invoices:
        by_supplier.setdefault(invoice["supplier"], []).append(invoice)
    rng = random.Random(int(hashlib.sha256(SEED.encode()).hexdigest(), 16))
    rows = []
    with zipfile.ZipFile(HERE / "data" / "statement-examples.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for index in range(COUNT):
            supplier = rng.choice(sorted(by_supplier))
            pool = by_supplier[supplier]
            chosen = sorted(
                rng.sample(pool, rng.randint(4, min(34, len(pool)))),
                key=lambda item: (item["invoice_date"], item["invoice_number"]),
            )
            listed = [
                {
                    "account": invoice["location"].split(" ")[0] if supplier == "Gordon Food Service" else "",
                    "number": invoice["invoice_number"],
                    "day": invoice["invoice_date"],
                    "amount": float(invoice["total"]),
                }
                for invoice in chosen
            ]
            customer = chosen[0]["location"].split(" ", 1)[-1] if supplier != "Gordon Food Service" else "GAS CITY LTD"
            name = f"statements/statement_{index + 1:03d}.pdf"
            archive.writestr(zipfile.ZipInfo(name, STAMP), draw(supplier, customer, listed, rng), zipfile.ZIP_DEFLATED)
            rows.append(
                json.dumps(
                    {
                        "statement": name,
                        "expected_supplier": supplier,
                        "expected_rows": [
                            {"invoice_number": row["number"], "invoice_date": row["day"], "amount": row["amount"]}
                            for row in listed
                        ],
                    }
                )
            )
        archive.writestr(zipfile.ZipInfo("examples.jsonl", STAMP), "\n".join(rows) + "\n", zipfile.ZIP_DEFLATED)
    (HERE / "data" / "statement-procedure.md").write_text(PROCEDURE)
    print(f"statement-examples.zip: {COUNT} drawn statements over {len(by_supplier)} suppliers")


PROCEDURE = """# Supplier statements

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
"""


if __name__ == "__main__":
    main()
