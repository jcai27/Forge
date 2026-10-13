"""Build the sales summary agent on the real summaries, through Agent Factory, and report how it did.

    cd apps/api && uv run python ../../demo/sales/build.py

The app must be running on a live model (bash demo/restaurant/start.sh). With thirteen documents there is
little to split: five for the builder to read and eight held back, which the builder never sees. The
score on those eight is the result, whatever it is. It spends a few cents on the model provider.
"""

import json
import os
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
REQUEST = (
    "Record a restaurant's sales summary from its point-of-sale system. You are given the text of the summary, "
    "which covers one day or one month. Return the restaurant, the first and last day covered as YYYY-MM-DD, "
    "gross sales, sales discounts and sales refunds as positive numbers, net sales, the tax amount, gratuity, "
    "tips collected, total guests, total orders, and the expected and actual closeout cash. Amounts in dollars."
)
TARGET, ROUNDS, MAX_COST = 0.8, 2, 3.0


def main():
    with httpx.Client(base_url=os.environ.get("FACTORY_API", "http://127.0.0.1:8000"), timeout=900) as api:

        def call(method, path, **request):
            response = api.request(method, path, **request)
            if response.status_code >= 400:
                raise SystemExit(f"{method} {path} answered {response.status_code}: {response.text[:500]}")
            return response.json()

        api.headers["Authorization"] = "Bearer " + call("POST", "/auth/demo")["token"]
        projects = call("GET", "/projects", params={"limit": 200})["items"]
        project = next((item for item in projects if item["name"] == "Sales desk"), None) or call(
            "POST",
            "/projects",
            json={"name": "Sales desk", "description": "Real point-of-sale summaries from a public bankruptcy docket"},
        )
        agent = call("POST", "/agents", json={"project_id": project["id"], "request": REQUEST, "minimum_score": TARGET})
        call(
            "POST",
            f"/agents/{agent['id']}/context",
            json={"name": "sales-procedure.md", "text": (HERE / "data" / "sales-procedure.md").read_text()},
        )
        with open(HERE / "data" / "sales-examples.zip", "rb") as archive:
            dataset = call(
                "POST",
                f"/agents/{agent['id']}/datasets/archive",
                files={"file": ("sales-examples.zip", archive, "application/zip")},
                data={"name": "Sales summaries", "development": 5, "selection": 0, "validation": 8},
            )
        print(
            f"Agent {agent['id']} ({agent['name']}): {dataset['rows']} summaries, split {dataset['profile']['splits']}"
        )
        build = call(
            "POST",
            f"/agents/{agent['id']}/builds",
            json={"max_iterations": ROUNDS, "max_cost": MAX_COST, "target_score": TARGET},
        )
        while True:
            job = call("GET", f"/builds/{build['id']}")
            if job["state"] in (
                "READY_FOR_REVIEW",
                "BELOW_TARGET",
                "BUDGET_EXHAUSTED",
                "FAILED",
                "CANCELLED",
                "STAGNATED",
                "PAUSED",
            ):
                break
            print(f"{job['state']}, round {job['iteration']}, ${job['spent']:.3f}", flush=True)
            time.sleep(20)
        card = job["checkpoint"].get("validation_scorecard") or {}
        print(
            json.dumps(
                {
                    "state": job["state"],
                    "held_back_score": card.get("score"),
                    "spent": round(job["spent"], 4),
                    "agent": agent["id"],
                    "build": build["id"],
                },
                indent=1,
            )
        )
        (HERE / "data" / "build.json").write_text(
            json.dumps({"agent": agent["id"], "build": build["id"], "state": job["state"], "scorecard": card}, indent=1)
        )
        print(f"http://localhost:3000/agents/{agent['id']}/build")


if __name__ == "__main__":
    main()
