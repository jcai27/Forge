"""How the answer key for the real sales summaries was made: read from each document's own text, and kept
only because the figures hold together.

    cd apps/api && uv run python ../../demo/sales/label.py     # rewrites labels.json from source/

The summaries come in three layouts. This reads the same fourteen figures from each and refuses any
document where gross sales less discounts less refunds is not net sales to the cent. It is the answer
key's maker, not the agent: the agent is built from examples in Agent Factory and never sees this.
"""

import json
import re
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).parent
# Filing, and the pages of it that are the summary (None: the whole filing).
FILINGS = {
    "33.2": None,
    "33.3": None,
    "93.5": [20, 21, 22, 23],
    "43.20": None,
    "58.13": None,
    "62.22": None,
    "71.14": None,
    "85.13": None,
    "86.10": None,
    "105.13": None,
    "115.13": None,
    "125.10": None,
    "133.6": None,
}
MONTHS = {
    m: i
    for i, m in enumerate(
        "January February March April May June July August September October November December".split(), 1
    )
}


def num(text):
    text = text.replace("$", "").replace(",", "").strip()
    return float(text) if text not in ("", "—", "-") else None


def first(pattern, text, flags=re.S):
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


def parse(text):
    out = {}
    m = re.search(r"SalesSummary_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", text)
    if m:
        out["period_start"], out["period_end"] = m.groups()
    else:
        m = re.search(r"([A-Z][a-z]+) (\d{1,2}), (\d{4}) - ([A-Z][a-z]+) (\d{1,2}), (\d{4})", text)
        if m:
            a, b, c, d, e, f = m.groups()
            out["period_start"], out["period_end"] = (
                f"{c}-{MONTHS[a]:02d}-{int(b):02d}",
                f"{f}-{MONTHS[d]:02d}-{int(e):02d}",
            )
    money = r"\s+(-?\$?-?[\d,]+\.?\d*)"
    for key, label in (
        ("net_sales", "Net sales"),
        ("gross_sales", "Gross sales"),
        ("discounts", "Sales discounts"),
        ("refunds", "Sales refunds"),
        ("tax", "Tax amount"),
        ("gratuity", "Gratuity"),
        ("tips", "Tips collected"),
        ("cash_expected", "Expected closeout cash"),
        ("cash_counted", "Actual closeout cash"),
    ):
        found = first(label + money, text)
        out[key] = abs(num(found)) if found and num(found) is not None else None
    for key, label in (("guests", "Total guests"), ("orders", "Total orders")):
        line = first(label + r"([^\n]+)", text)
        numbers = re.findall(r"[\d,]+", line or "")
        out[key] = int(numbers[-1].replace(",", "")) if numbers else None
    return out


def text_of(path, pages=None):
    reader = PdfReader(path)
    chosen = reader.pages if pages is None else [reader.pages[i] for i in pages]
    return "\n".join(p.extract_text(extraction_mode="layout") or "" for p in chosen)


def main():
    out = []
    for name, pages in FILINGS.items():
        source = f"gov.uscourts.mdb.783876.{name}.pdf"
        got = parse(text_of(HERE / "source" / source, pages))
        if (
            None in got.values()
            or abs(got["gross_sales"] - got["discounts"] - got["refunds"] - got["net_sales"]) > 0.011
        ):
            raise SystemExit(f"{source} does not hold together: {got}")
        out.append({"source": source, "pages": pages, "restaurant": "Smokecraft Modern Barbecue", **got})
    (HERE / "labels.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"labels.json: {len(out)} summaries, each adding up")


if __name__ == "__main__":
    main()
