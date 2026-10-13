"""Real point-of-sale sales summaries, from a public bankruptcy docket, as examples for an agent.

A restaurant in Chapter 11 files a monthly operating report, and this one attached its point-of-sale
system's sales summary to each. Federal filings are public and the RECAP archive (courtlistener.com)
serves them free. The thirteen summaries used here are from In re Smokecraft Clarendon, LLC, Bankr.
D. Md. 24-13609: two single days in April 2024 and eleven months from May 2024 to April 2025
(September 2024 is not in the archive). Nothing in them has been changed.

    cd apps/api && uv run python ../../demo/sales/prepare.py

Downloads the filings into demo/sales/source/ (once) and writes demo/sales/data/sales-examples.zip:
one PDF per summary, as filed, and the answers. Where a summary is part of a longer report, only its
own pages are cut out; no page is altered.

Where the answers come from. labels.json holds fourteen figures for each summary, read from the
document's own text by a parser written for its three layouts, and kept only because they hold
together: gross sales less discounts less refunds equals net sales to the cent in every one. Six of
the thirteen were also checked by eye against the printed lines. The parser is not the agent, and
the agent never sees it: it is how the answer key was made.
"""

import io
import json
import urllib.request
import zipfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

HERE = Path(__file__).parent
SOURCE, OUT = HERE / "source", HERE / "data"
RECAP = "https://storage.courtlistener.com/recap/gov.uscourts.mdb.783876/"
STAMP = (2025, 5, 26, 0, 0, 0)
FIELDS = (
    "restaurant", "period_start", "period_end", "gross_sales", "discounts", "refunds", "net_sales", "tax",
    "gratuity", "tips", "guests", "orders", "cash_expected", "cash_counted",
)  # fmt: skip
PROCEDURE = """# Point-of-sale sales summaries

How a restaurant's sales summary from its point-of-sale system is recorded. Written for this demonstration.

A summary covers one day or one month. The same figures are printed in more than one layout: as a list of
labels and amounts, or as a row of headings with a row of amounts under it.

- **restaurant**: the location the summary is for, as printed.
- **period_start**, **period_end**: the first and last day covered, as YYYY-MM-DD. The same day twice for a
  one-day summary.
- **gross_sales**: sales before discounts and refunds.
- **discounts**: sales discounts, as a positive number, though it is printed with a minus sign.
- **refunds**: sales refunds, as a positive number.
- **net_sales**: gross sales less discounts and refunds. The figure for the whole period, not for one
  service mode, category or revenue centre.
- **tax**: the tax amount in the revenue summary, not the taxable amount and not one tax rate's share.
- **gratuity**: the gratuity in the revenue summary.
- **tips**: tips collected, before any are withheld.
- **guests**, **orders**: total guests and total orders across all service modes: the Total column, not Quick
  Service or Table Service alone.
- **cash_expected**, **cash_counted**: the expected and the actual closeout cash.

Amounts are in dollars, as numbers, with no currency sign or thousands separator.
"""


def main():
    SOURCE.mkdir(exist_ok=True)
    (OUT).mkdir(exist_ok=True)
    labels = json.loads((HERE / "labels.json").read_text())
    rows = []
    with zipfile.ZipFile(OUT / "sales-examples.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for label in labels:
            target = SOURCE / label["source"]
            if not target.exists():
                print(f"Downloading {label['source']}")
                with urllib.request.urlopen(RECAP + label["source"], timeout=300) as response:
                    target.write_bytes(response.read())
            data = target.read_bytes()
            if label["pages"]:
                reader, writer = PdfReader(target), PdfWriter()
                for index in label["pages"]:
                    writer.add_page(reader.pages[index])
                buffer = io.BytesIO()
                writer.write(buffer)
                data = buffer.getvalue()
            name = f"summaries/sales_{label['period_start']}_{label['period_end']}.pdf"
            archive.writestr(zipfile.ZipInfo(name, STAMP), data, zipfile.ZIP_DEFLATED)
            rows.append(json.dumps({"summary": name, **{f"expected_{field}": label[field] for field in FIELDS}}))
        archive.writestr(zipfile.ZipInfo("examples.jsonl", STAMP), "\n".join(rows) + "\n", zipfile.ZIP_DEFLATED)
    (OUT / "sales-procedure.md").write_text(PROCEDURE)
    print(f"sales-examples.zip: {len(rows)} real sales summaries")


if __name__ == "__main__":
    main()
