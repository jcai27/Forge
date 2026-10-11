"""Run the held-back week of invoices through the deployed agent and report what it recorded.

Each scanned invoice is read by the platform, the deployed agent records its header and every line,
and the result is compared with the answer key. The agent never sees the key. Writes
data/batch-report.html, in which every invoice links to its page in the app: the scan beside the
agent's answer.

    cd apps/api && uv run python ../../demo/restaurant/run_batch.py AGENT_ID

The agent must have an active deployment and the app must run with DOCUMENT_READING=true. Every
invoice is one production run on a live model; a run already made for an invoice is reused, so the
script can be stopped and started again.
"""

import argparse
import html
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from factory.tables import match_rows, same, wrong_fields  # noqa: E402
from setup import sign_in  # noqa: E402

DATA = Path(__file__).parent / "data"
HEADER = ("supplier", "customer", "invoice_number", "invoice_date", "total_cents", "tax_cents")
APP = os.environ.get("FACTORY_APP", "http://localhost:3000")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("agent", help="the agent's id, from its address in the browser")
    parser.add_argument("--limit", type=int, default=0, help="only the first N invoices")
    parser.add_argument("--label", default="batch", help="names this pass; a new label runs every invoice again")
    options = parser.parse_args()
    key = json.loads((DATA / "batch-answer-key.json").read_text())

    with httpx.Client(base_url=os.environ.get("FACTORY_API", "http://127.0.0.1:8000"), timeout=900) as api:

        def call(method, path, **request):
            response = api.request(method, path, **request)
            if response.status_code >= 400:
                raise SystemExit(f"{method} {path} answered {response.status_code}: {response.text[:500]}")
            return response.json()

        sign_in(api, call)
        deployments = call("GET", f"/agents/{options.agent}/deployments", params={"limit": 200})["items"]
        deployment = next((item for item in deployments if item["active"]), None)
        if deployment is None:
            raise SystemExit("This agent has no active deployment. Approve a version and deploy it first.")
        rows, reading = [], 0.0
        with zipfile.ZipFile(DATA / "batch-invoices.zip") as archive:
            table = [json.loads(line) for line in io.StringIO(archive.read("invoices.jsonl").decode()) if line.strip()]
            for position, packet in enumerate(table[: options.limit or None], 1):
                name = packet["invoice"]
                upload = {"file": (name.rsplit("/", 1)[-1], archive.read(name), "application/pdf")}
                # Read the way the deployed version was built to have its documents read, and keep the page
                # images so each run's page in the app shows the scan beside the answer.
                read = call(
                    "POST",
                    "/documents/text",
                    files=upload,
                    data={"deployment_id": deployment["id"], "keep_pages": "true"},
                )
                reading += read["reading"]["cost"]
                run = call(
                    "POST",
                    f"/deployments/{deployment['id']}/invoke",
                    json={
                        "input": {"text": read["text"]},
                        "idempotency_key": f"{options.label}-{name}",
                    },
                )
                output = run.get("output") if run.get("status") == "completed" else None
                rows.append(judge(key[name], output, run))
                done = rows[-1]
                print(
                    f"{position}/{len(table)} {name}: header {done['header_right']}/{len(HEADER)}, "
                    f"lines {done['lines_right']}/{done['lines']}"
                    + (f", {done['extra']} not expected" if done["extra"] else "")
                    + ("" if output else f" ({run.get('status')}: {run.get('error')})"),
                    flush=True,
                )
    report(rows, reading + sum((row["run"].get("metrics") or {}).get("cost") or 0 for row in rows))


def judge(expected, output, run):
    """One invoice against its key, by the platform's own rules for comparing values and lining up rows."""
    output = output or {}
    header = {field: same(expected[field], output.get(field)) for field in HEADER}
    pairs, extra = match_rows(expected["items"], output.get("items"))
    wrong = [(wanted, given, wrong_fields(wanted, given)) for wanted, given in pairs]
    return {
        "expected": expected,
        "output": output,
        "run": run,
        "header": header,
        "header_right": sum(header.values()),
        "lines": len(pairs),
        "lines_right": sum(not fields for _, _, fields in wrong),
        "wrong": [(wanted, given, fields) for wanted, given, fields in wrong if fields],
        "extra": len(extra),
    }


def report(rows, cost):
    lines, right = sum(row["lines"] for row in rows), sum(row["lines_right"] for row in rows)
    whole = sum(
        row["header_right"] == len(HEADER) and row["lines_right"] == row["lines"] and not row["extra"] for row in rows
    )
    summary = [
        ("Scanned invoices recorded", len(rows)),
        ("Header fields right", f"{sum(row['header_right'] for row in rows)} of {len(rows) * len(HEADER)}"),
        ("Line items right in every field", f"{right} of {lines}" + (f" ({right / lines:.1%})" if lines else "")),
        ("Lines the agent added that are not on the invoice", sum(row["extra"] for row in rows)),
        ("Invoices right in every field and line", f"{whole} of {len(rows)}"),
        ("Model cost, reading included", f"${cost:,.2f}"),
    ]
    print()
    for label, value in summary:
        print(f"{label}: {value}")

    def line(row):
        expected, output = row["expected"], row["output"]
        clean = row["header_right"] == len(HEADER) and row["lines_right"] == row["lines"] and not row["extra"]
        header = ", ".join(field for field, ok in row["header"].items() if not ok) or "all right"
        cells = [
            expected["customer"],
            expected["invoice_number"],
            expected["invoice_date"],
            f"${expected['total_cents'] / 100:,.2f}",
            header,
            f"{row['lines_right']} of {row['lines']}" + (f", {row['extra']} added" if row["extra"] else ""),
        ]
        mark = "right" if clean else "wrong"
        body = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells)
        link = f'<td><a href="{APP}/runs/{html.escape(row["run"]["id"])}">Open scan and answer</a></td>'
        detail = ""
        if row["wrong"] and output:
            # Up to five of the lines that differ, so the report says what kind of mistake it was.
            shown = "".join(
                f"<li>{html.escape(str(wanted.get('description')))}: "
                + (
                    "; ".join(f"{field} {given.get(field)!r}, should be {wanted.get(field)!r}" for field in fields)
                    if given
                    else "missing"
                )
                + "</li>"
                for wanted, given, fields in row["wrong"][:5]
            )
            detail = f'<tr class="detail"><td colspan="7"><ul>{html.escape("")}{shown}</ul></td></tr>'
        return f'<tr class="{mark}">{body}{link}</tr>{detail}'

    facts = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>" for label, value in summary
    )
    page = f"""<!doctype html><meta charset="utf-8"><title>Invoice batch report</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:1080px;margin:40px auto;padding:0 16px;color:#1a1d21}}
h1{{font-size:22px}} table{{border-collapse:collapse;width:100%;margin:16px 0}}
td,th{{text-align:left;padding:6px 10px;border-bottom:1px solid #e3e5e8;vertical-align:top}} th{{font-size:13px;color:#5b6370}}
tr.wrong td:nth-child(6){{color:#b3261e;font-weight:600}} tr.right td:nth-child(6){{color:#1b7f4b}}
tr.detail td{{font-size:13px;color:#5b6370;border-bottom:1px solid #e3e5e8}} tr.detail ul{{margin:0;padding-left:18px}}
p.note{{color:#5b6370;font-size:13px}}
</style>
<h1>Gordon Food Service invoices, 20 to 25 October 2010</h1>
<p class="note">Real invoices, unchanged, from a public bankruptcy court exhibit (In re Gas City, Ltd.). The agent worked
from the scans and never saw the answers. Invoice numbers, dates and totals are checked against the supplier's own
summary filed with the court. Line items are checked against a reading of each page in which every line's quantity
times price equals its amount and the lines add up to the invoice total. A description counts as right when it is
nearly the same reading; codes and numbers must match exactly.</p>
<table>{facts}</table>
<table><tr><th>Location</th><th>Invoice</th><th>Date</th><th>Total</th><th>Header</th><th>Lines right</th>
<th></th></tr>
{"".join(line(row) for row in rows)}</table>
"""
    (DATA / "batch-report.html").write_text(page)
    print(f"\nReport: {DATA / 'batch-report.html'}")


if __name__ == "__main__":
    main()
