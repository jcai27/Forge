"""Real supplier invoices for the restaurant demo, from public court records.

When a food distributor sues over unpaid bills, or claims in a bankruptcy, it files the invoices as
exhibits. Federal filings are public and the RECAP archive (courtlistener.com) serves them free. The
three exhibits used here are scanned invoices from Gordon Food Service to a group of Indiana diners
and truck stops (October 2010), from W.R. Vernon Produce and from Gramercy Produce. Nothing in them
has been changed.

    cd apps/api && uv run python ../../demo/restaurant/prepare.py              # everything
    cd apps/api && uv run python ../../demo/restaurant/prepare.py --examples 30 --batch 8   # a small demo

Downloads the exhibits into demo/restaurant/source/ (once) and writes into demo/restaurant/data/:

  invoice-examples.zip    one scanned PDF per invoice, the location's price history, the answers
  batch-invoices.zip      the last week of the Gordon Food Service invoices, with no answers
  batch-answer-key.json   the answers for that batch
  price-findings.csv      every price rise over the limit in the whole set, with what it cost

The task: read the scan and record everything on it that the answer key can vouch for. That is the
supplier, the customer, the invoice number, date, total and tax, and every line: item code where
the supplier prints one, description, quantity, unit price and amount.

Price rises are not the agent's job. Comparing a price with the last one paid is arithmetic over
recorded lines, which the customer portal does in code (factory/portal.py). This script works the
same comparison out from the answer key, as a check on what the portal should find.

Where the answers come from. labels.json holds each invoice's lines as a model read them from the
page images. An invoice is in it only if every line's quantity times price equals its amount and the
lines add up to the printed total; for Gordon Food Service the number, date and total also had to
match the supplier's own summary of the invoices, filed in the same exhibit. Invoices that did not
pass were left out, so this set leans towards pages that read cleanly.
"""

import argparse
import csv
import io
import json
import re
import urllib.request
import zipfile
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pypdf import PdfReader, PdfWriter

HERE = Path(__file__).parent
SOURCE, OUT = HERE / "source", HERE / "data"
RECAP = "https://storage.courtlistener.com/recap/"
EXHIBITS = {
    # In re Gas City, Ltd., Bankr. N.D. Ill. 10-47879, document 427: Gordon Food Service's invoices.
    "gov.uscourts.ilnb.1054045.427.2.pdf": "gov.uscourts.ilnb.1054045/",
    "gov.uscourts.ilnb.1054045.427.3.pdf": "gov.uscourts.ilnb.1054045/",
    "gov.uscourts.ilnb.1054045.427.4.pdf": "gov.uscourts.ilnb.1054045/",
    "gov.uscourts.ilnb.1054045.427.5.pdf": "gov.uscourts.ilnb.1054045/",
    # M.D.N.C. docket 71157, document 5 exhibit 2: W.R. Vernon Produce invoices.
    "gov.uscourts.ncmd.71157.5.2.pdf": "gov.uscourts.ncmd.71157/",
    # S.D.N.Y. docket 496593, document 1 exhibit 1: Gramercy Produce invoices.
    "gov.uscourts.nysd.496593.1.1.pdf": "gov.uscourts.nysd.496593/",
}
LIMIT = Decimal("1.05")
BATCH_FROM = date(2010, 10, 20)
STAMP = (2010, 10, 25, 0, 0, 0)
# Label dates far from the rest of an exhibit are misreadings of a faint scan.
PLAUSIBLE = {"W.R. Vernon Produce": ("2015-06", "2016-06"), "Gramercy Produce": ("2017-06", "2018-06")}


def cents(value):
    return int((Decimal(value) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def item_key(invoice, line):
    # Gordon Food Service prints an item code. The produce houses print only a name: what sits in
    # their first column is the country of origin.
    if invoice["supplier"] == "Gordon Food Service" and (line["code"] or "").strip():
        return line["code"].strip()
    return re.sub(r"\s+", " ", line["description"].upper()).strip()


def customer(location):
    """The customer's name: the location as labelled, without the account number in front of it."""
    first, _, rest = location.strip().partition(" ")
    return rest.strip() if rest and any(character.isdigit() for character in first) else location.strip()


def units(line):
    """What the unit price multiplies: pounds for an item sold by weight, otherwise the quantity."""
    weight = re.search(r"([\d.]+)\s*LB\s*$", line["description"].strip())
    quantity, price, amount = Decimal(line["quantity"]), Decimal(line["unit_price"]), Decimal(line["amount"])
    if abs(quantity * price - amount) <= Decimal("0.011") or not weight:
        return quantity
    return Decimal(weight.group(1))


def fetch():
    SOURCE.mkdir(exist_ok=True)
    for name, folder in EXHIBITS.items():
        target = SOURCE / name
        if not target.exists():
            print(f"Downloading {name}")
            with urllib.request.urlopen(RECAP + folder + name, timeout=300) as response:
                target.write_bytes(response.read())


def invoice_pdf(readers, pages):
    writer = PdfWriter()
    for name, index in pages:
        writer.add_page(readers[name].pages[index])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def history_text(book):
    if not book:
        return "No earlier purchases on record for this location."
    rows = ["Last price paid at this location before this invoice", "ITEM  |  DESCRIPTION  |  LAST PRICE  |  DATE"]
    rows += [
        f"{key}  |  {description}  |  {price}  |  {day}" for key, (price, day, description) in sorted(book.items())
    ]
    return "\n".join(rows)


def spread(cases, count):
    """About count of the cases, taken evenly through the list so that suppliers and dates keep their shares."""
    if not count or count >= len(cases):
        return cases
    return [cases[round(index * (len(cases) - 1) / (count - 1))] for index in range(count)] if count > 1 else cases[:1]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--examples", type=int, default=0, help="write only this many example invoices (default: all)")
    parser.add_argument("--batch", type=int, default=0, help="write only this many batch invoices (default: all)")
    options = parser.parse_args()
    invoices = json.loads((HERE / "labels.json").read_text())
    kept = []
    for invoice in invoices:
        window = PLAUSIBLE.get(invoice["supplier"])
        if window and not window[0] <= invoice["invoice_date"][:7] <= window[1]:
            continue
        kept.append(invoice)
    kept.sort(key=lambda invoice: (invoice["supplier"], invoice["invoice_date"], invoice["invoice_number"]))
    fetch()
    readers = {name: PdfReader(SOURCE / name) for name in EXHIBITS}

    books, findings, cases = {}, [], []
    for invoice in kept:
        book = books.setdefault((invoice["supplier"], invoice["location"]), {})
        risen, items = 0, []
        for line in invoice["lines"]:
            key, price = item_key(invoice, line), Decimal(line["unit_price"])
            rose = key in book and price > book[key][0] * LIMIT
            item = {"code": (line["code"] or "").strip()} if invoice["supplier"] == "Gordon Food Service" else {}
            items.append(
                {
                    **item,
                    "description": line["description"].strip(),
                    "quantity": float(line["quantity"]),
                    "unit_price": float(line["unit_price"]),
                    "amount": float(line["amount"]),
                }
            )
            if rose:
                risen += 1
                extra = ((price - book[key][0]) * units(line)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                findings.append(
                    [
                        invoice["supplier"],
                        invoice["location"],
                        invoice["invoice_number"],
                        invoice["invoice_date"],
                        key,
                        line["description"],
                        book[key][0],
                        book[key][1],
                        price,
                        f"{(price / book[key][0] - 1) * 100:.1f}",
                        extra,
                    ]
                )
        cases.append(
            {
                "invoice": invoice,
                "name": f"invoices/{invoice['supplier'].split()[0].lower()}_{invoice['invoice_number']}.pdf",
                "pdf": invoice_pdf(readers, invoice["pages"]),
                "history": history_text(book),
                "risen": risen,
                "answer": {
                    "supplier": invoice["supplier"],
                    "customer": customer(invoice["location"]),
                    "invoice_number": invoice["invoice_number"],
                    "invoice_date": invoice["invoice_date"],
                    "total_cents": cents(invoice["total"]),
                    "tax_cents": cents(invoice.get("tax", "0")),
                    "items": items,
                },
            }
        )
        # The book moves on only after the invoice is judged: an invoice is compared with what came before it.
        for line in invoice["lines"]:
            book[item_key(invoice, line)] = (Decimal(line["unit_price"]), invoice["invoice_date"], line["description"])

    def in_batch(case):
        invoice = case["invoice"]
        return (
            invoice["supplier"] == "Gordon Food Service" and date.fromisoformat(invoice["invoice_date"]) >= BATCH_FROM
        )

    # Prices are compared across the whole set before any of it is left out: a smaller demo is the
    # same invoices with the same answers, only fewer of them.
    examples = spread([case for case in cases if not in_batch(case)], options.examples)
    batch = spread([case for case in cases if in_batch(case)], options.batch)
    OUT.mkdir(exist_ok=True)
    for path, table, chosen, with_answers in (
        ("invoice-examples.zip", "examples.jsonl", examples, True),
        ("batch-invoices.zip", "invoices.jsonl", batch, False),
    ):
        rows = []
        with zipfile.ZipFile(OUT / path, "w", zipfile.ZIP_DEFLATED) as archive:
            for case in chosen:
                archive.writestr(zipfile.ZipInfo(case["name"], STAMP), case["pdf"], zipfile.ZIP_DEFLATED)
                row = {"invoice": case["name"]}
                if with_answers:
                    # The line items are a table, which a JSON Lines file can hold and a CSV cannot.
                    row.update({f"expected_{field}": value for field, value in case["answer"].items()})
                rows.append(json.dumps(row))
            archive.writestr(zipfile.ZipInfo(table, STAMP), "\n".join(rows) + "\n", zipfile.ZIP_DEFLATED)
        risen = sum(1 for case in chosen if case["risen"])
        pages = sum(len(case["invoice"]["pages"]) for case in chosen)
        lines = sum(len(case["answer"]["items"]) for case in chosen)
        print(
            f"{path}: {len(chosen)} invoices, {pages} scanned pages, {lines} line items, "
            f"{risen} invoices with a price rise over the limit"
        )
    key = {case["name"]: {"location": case["invoice"]["location"], **case["answer"]} for case in batch}
    (OUT / "batch-answer-key.json").write_text(json.dumps(key, indent=1) + "\n")
    with open(OUT / "price-findings.csv", "w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "supplier",
                "location",
                "invoice",
                "date",
                "item",
                "description",
                "last_price",
                "last_date",
                "price",
                "rise_percent",
                "extra_cost",
            ]
        )
        writer.writerows(findings)
    print(
        f"{len(findings)} price rises over 5%, costing ${sum(row[-1] for row in findings):,.2f} against the last price paid"
    )


if __name__ == "__main__":
    main()
