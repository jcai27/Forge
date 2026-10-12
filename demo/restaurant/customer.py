"""Set up the customer side of the demo: a customer's own workspace with the invoice agent at work in it.

Opens a workspace for a customer, installs the deployed invoice agent there, sends the Gordon Food
Service invoices through it in date order as if they had arrived one by one, and creates a login
for one of the customer's people.

    cd apps/api && uv run python ../../demo/restaurant/customer.py AGENT_ID

AGENT_ID is the builder-side agent, which must have an active deployment. The app must run with
DOCUMENT_READING=true. Each invoice is read and processed on a live model in the customer's
workspace, charged there. Run it again and it carries on: a file already taken in is not read twice.
"""

import argparse
import io
import json
import os
import secrets
import zipfile
from pathlib import Path

import httpx
from pypdf import PdfReader, PdfWriter
from setup import sign_in

HERE = Path(__file__).parent
CUSTOMER = "Steel City Diners"
LOGIN = "owner@steelcity-demo.example"
# Invoices in the exhibits that have no answer in labels.json, because the reading used to write the
# answers did not add up. The customer received them all the same, and the supplier's statement lists
# them: left out, each would show as billed and never received, which is not what happened.
UNKEYED = {"131877288": ("2010-10-12", "gov.uscourts.ilnb.1054045.427.5.pdf", (12, 13, 14))}
# Kept out of the customer's workspace so they can be uploaded in front of someone: three invoices from
# the last days of the set, of one and two pages. reset.py takes them back out after each showing.
HELD_BACK = ("132029719", "821095277", "132011648")
STATEMENT = ("GFS statement October 2010.pdf", "gov.uscourts.ilnb.1054045.427.1.pdf")


def cut(source, pages):
    writer = PdfWriter()
    for index in pages:
        writer.add_page(PdfReader(HERE / "source" / source).pages[index])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def invoice_files():
    """Every Gordon Food Service invoice in the exhibits as (date, PDF bytes), by invoice number."""
    dates = {
        invoice["invoice_number"]: invoice["invoice_date"]
        for invoice in json.loads((HERE / "labels.json").read_text())
        if invoice["supplier"] == "Gordon Food Service"
    }
    files = {}
    for name in ("invoice-examples.zip", "batch-invoices.zip"):
        with zipfile.ZipFile(HERE / "data" / name) as archive:
            for member in archive.namelist():
                if member.startswith("invoices/gordon_"):
                    files[member.rsplit("_", 1)[-1].removesuffix(".pdf")] = archive.read(member)
    for number, (issued, source, pages) in UNKEYED.items():
        dates[number], files[number] = issued, cut(source, pages)
    return {number: (dates[number], files[number]) for number in files}


def file_name(number):
    return f"GFS invoice {number}.pdf"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("agent", help="the builder-side agent's id, from its address in the browser")
    parser.add_argument("--limit", type=int, default=0, help="only the first N invoices")
    parser.add_argument("--statements", help="the builder-side statement-reading agent's id, to install it as well")
    options = parser.parse_args()
    invoices = invoice_files()
    ordered = sorted((n for n in invoices if n not in HELD_BACK), key=lambda number: (invoices[number][0], number))

    with httpx.Client(base_url=os.environ.get("FACTORY_API", "http://127.0.0.1:8000"), timeout=900) as api:

        def call(method, path, **request):
            response = api.request(method, path, **request)
            if response.status_code >= 400:
                raise SystemExit(f"{method} {path} answered {response.status_code}: {response.text[:500]}")
            return response.json() if response.content else None

        sign_in(api, call)
        builder = api.headers["Authorization"]
        deployments = call("GET", f"/agents/{options.agent}/deployments", params={"limit": 200})["items"]
        deployment = next((item for item in deployments if item["active"]), None)
        if deployment is None:
            raise SystemExit("This agent has no active deployment. Approve a version and deploy it first.")
        customer = next((item for item in call("GET", "/customers")["items"] if item["name"] == CUSTOMER), None)
        if customer is None:
            customer = call("POST", "/customers", json={"name": CUSTOMER})
        if not customer["operations"]:
            customer = call(
                "POST",
                f"/customers/{customer['id']}/operations",
                json={"deployment_id": deployment["id"], "name": "Supplier invoices"},
            )
        if options.statements and not any(item["kind"] == "statement" for item in customer["operations"]):
            reader = next(
                (
                    item
                    for item in call("GET", f"/agents/{options.statements}/deployments", params={"limit": 200})["items"]
                    if item["active"]
                ),
                None,
            )
            if reader is None:
                raise SystemExit("The statement agent has no active deployment.")
            customer = call(
                "POST",
                f"/customers/{customer['id']}/operations",
                json={"deployment_id": reader["id"], "name": "Supplier statements"},
            )
        if not customer["customer_members"]:
            # One of the customer's people: invited by the builder, registered, and joined with the code.
            invitation = call("POST", f"/customers/{customer['id']}/invitations", json={"email": LOGIN})
            password = secrets.token_urlsafe(12)
            del api.headers["Authorization"]
            joined = call(
                "POST", "/auth/register", json={"email": LOGIN, "password": password, "organization": "Personal"}
            )
            api.headers["Authorization"] = "Bearer " + joined["token"]
            call("POST", "/organization-invitations/accept", json={"token": invitation["token"]})
            api.headers["Authorization"] = builder
            print(f"Customer login: {LOGIN} / {password}  (local demo only; shown once)")

        there = call("POST", "/auth/switch-organization", json={"org_id": customer["id"]})
        api.headers["Authorization"] = "Bearer " + there["token"]
        operations = call("GET", "/portal/me")["operations"]
        operation = next(item for item in operations if item["kind"] == "invoice")
        chosen = ordered[: options.limit or None]
        for position, number in enumerate(chosen, 1):
            upload = {"file": (file_name(number), io.BytesIO(invoices[number][1]), "application/pdf")}
            made = call("POST", f"/portal/operations/{operation['id']}/documents", files=upload)
            print(
                f"{position}/{len(chosen)} {invoices[number][0]} invoice {number}: {made['status']}"
                + (" (already here)" if made["duplicate"] else "")
                + (f" {made['error']}" if made.get("error") else ""),
                flush=True,
            )
        # The ledger accounts a diner would code food suppliers to, so approved invoices can go to the books.
        call(
            "PUT",
            f"/portal/operations/{operation['id']}/settings",
            json={
                "accounts": [
                    {"code": "5000", "name": "Food cost"},
                    {"code": "5100", "name": "Produce"},
                    {"code": "6200", "name": "Supplies"},
                ],
                "default_account": "5000",
                "supplier_accounts": {"Gordon Food Service": "5000"},
                "terms_days": 28,
            },
        )
        stages = call("POST", f"/portal/operations/{operation['id']}/recheck")
        print(f"\nAfter the automatic checks: {stages}")
        statements = next((item for item in operations if item["kind"] == "statement"), None)
        if statements:
            # The one real statement: Gordon Food Service's own summary of its invoices, as filed with the court.
            upload = {"file": (STATEMENT[0], (HERE / "source" / STATEMENT[1]).read_bytes(), "application/pdf")}
            made = call("POST", f"/portal/operations/{statements['id']}/documents", files=upload)
            if made["status"] == "processed":
                found = call("GET", f"/portal/documents/{made['id']}/reconciliation")
                key = json.loads((HERE / "statement-key.json").read_text())["rows"]
                read = {(str(row["invoice_number"]), row["amount"]) for row in found["rows"]}
                right = sum((row["invoice_number"], row["amount"]) in read for row in key)
                print(
                    f"Statement: {len(found['rows'])} rows read, {right} of {len(key)} match the key. Against the invoices: {found['counts']}"
                )
            else:
                print(f"Statement: {made['status']} {made.get('error')}")
        seen = call("GET", f"/portal/operations/{operation['id']}/insights")
        print(
            f"\n{seen['documents']} invoices recorded, {len(seen['price_rises'])} price rises over {seen['threshold_percent']:g}%"
        )
        for rise in seen["price_rises"][:8]:
            print(
                f"  {rise['date']} {rise['customer']}: {rise['description']} {rise['last_price']} -> {rise['price']} (+{rise['rise_percent']}%)"
            )
        print("\nPortal: http://localhost:3000/portal  (sign in as the customer, or open it from Customers)")


if __name__ == "__main__":
    main()
