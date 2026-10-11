"""Set the restaurant demo up in a running workspace and start its build.

Creates the invoice agent, attaches the desk procedure and the scanned example invoices, and starts
a build. Everything it does can also be done by hand in the Create agent form; this is the same
sequence of requests.

    cd apps/api && uv run python ../../demo/restaurant/setup.py

The app must be running with DOCUMENT_READING=true on a model that reads images: the upload sends
each scanned page to the model before the build starts. That and the build both spend money. Signs
in to the local demo workspace; for another one set FACTORY_API, FACTORY_EMAIL and FACTORY_PASSWORD.
"""

import argparse
import os
from pathlib import Path

import httpx

DATA = Path(__file__).parent / "data"
PROJECT = "Invoice desk"
REQUEST = (
    "Record each supplier invoice in full. You are given the text read from a scanned invoice. Return the supplier, "
    "the customer, the invoice number, the invoice date as YYYY-MM-DD, the invoice total in cents, the tax charged "
    "in cents (0 when there is none), and every line of "
    "the invoice as a row of items: item code where one is printed, description, quantity, unit price and amount."
)


STATEMENT_REQUEST = (
    "Record a supplier's statement. You are given the text of a statement that lists invoices the supplier has "
    "billed. Return the supplier, and one row for every invoice listed: its invoice number, its date as "
    "YYYY-MM-DD and its amount in dollars."
)


def sign_in(api, call):
    if os.environ.get("FACTORY_EMAIL"):
        credentials = {"email": os.environ["FACTORY_EMAIL"], "password": os.environ["FACTORY_PASSWORD"]}
        session = call("POST", "/auth/login", json=credentials)
    else:
        session = call("POST", "/auth/demo")
    api.headers["Authorization"] = "Bearer " + session["token"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--development", type=int, default=30, help="examples the builder reads")
    parser.add_argument("--selection", type=int, default=20, help="examples each change is scored on")
    parser.add_argument("--validation", type=int, default=36, help="examples held back for the final result")
    parser.add_argument("--target", type=float, default=0.8, help="score required for approval")
    parser.add_argument("--rounds", type=int, default=4, help="improvement rounds before the build stops")
    parser.add_argument("--max-cost", type=float, default=25, help="ceiling on the build's model spend, USD")
    parser.add_argument("--reading-max-cost", type=float, default=15, help="ceiling on reading scanned pages, USD")
    parser.add_argument("--no-build", action="store_true", help="attach everything but do not start a build")
    parser.add_argument(
        "--statements", action="store_true", help="build the statement reader instead of the invoice reader"
    )
    options = parser.parse_args()
    request, examples = REQUEST, "invoice-examples.zip"
    procedure = DATA / "invoice-desk-procedure.md"
    if options.statements:
        request, examples, procedure = STATEMENT_REQUEST, "statement-examples.zip", DATA / "statement-procedure.md"

    with httpx.Client(base_url=os.environ.get("FACTORY_API", "http://127.0.0.1:8000"), timeout=3600) as api:

        def call(method, path, **request):
            response = api.request(method, path, **request)
            if response.status_code >= 400:
                raise SystemExit(f"{method} {path} answered {response.status_code}: {response.text[:500]}")
            return response.json()

        sign_in(api, call)
        projects = call("GET", "/projects", params={"limit": 200})["items"]
        project = next((item for item in projects if item["name"] == PROJECT), None) or call(
            "POST", "/projects", json={"name": PROJECT, "description": "Real supplier invoices from court records"}
        )
        agent = call(
            "POST", "/agents", json={"project_id": project["id"], "request": request, "minimum_score": options.target}
        )
        call("POST", f"/agents/{agent['id']}/context", json={"name": procedure.name, "text": procedure.read_text()})
        print("Reading the examples. Scanned pages take several minutes.")
        with open(DATA / examples, "rb") as archive:
            dataset = call(
                "POST",
                f"/agents/{agent['id']}/datasets/archive",
                files={"file": (examples, archive, "application/zip")},
                data={
                    "name": "Statement examples" if options.statements else "Invoice examples",
                    "development": options.development,
                    "selection": options.selection,
                    "validation": options.validation,
                    "reading_max_cost": options.reading_max_cost,
                },
            )
        print(f"Agent {agent['id']}: {dataset['rows']} invoices, split {dataset['profile']['splits']}")
        print(f"Reading: {dataset['reading']}")
        if not options.no_build:
            build = call(
                "POST",
                f"/agents/{agent['id']}/builds",
                json={"max_iterations": options.rounds, "max_cost": options.max_cost, "target_score": options.target},
            )
            print(f"Build {build['id']} started")
        print(f"Open http://localhost:3000/agents/{agent['id']}/build")


if __name__ == "__main__":
    main()
