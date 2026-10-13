"""Build the operations demo from nothing: the agents, the workspace, and the last week's documents read into it.

    bash demo/operations/build.sh                  # everything
    bash demo/operations/build.sh --only till      # one agent
    bash demo/operations/build.sh --documents-only # just draw the documents

The app must be running on a live model (bash demo/restaurant/start.sh). For each kind of document it:

  1. creates an agent in the local demo builder workspace, with its procedure and 24 example documents,
     and runs a build: 8 examples for the builder to read, 6 to score changes on, 10 held back;
  2. approves and deploys the version the build ends on, if it met its target on the held-back examples;
  3. installs it in Harbor Table Group and sends the last week's documents through it.

Then it checks every reading against the answers and says how many match. Everything spends money on
the model provider, a few cents an agent. Run it again and it carries on: an agent already deployed is
not built twice, and a document already taken in is not read twice.
"""

import argparse
import json
import os
import time
from pathlib import Path

import httpx
from documents import DATA, LABELS, REQUESTS, write
from sample import GROUP

HERE = Path(__file__).parent
STATE = DATA / "agents.json"
PROJECT = "Operations desk"
TARGET, ROUNDS, MAX_COST = 0.7, 2, 2.0
DONE = ("READY_FOR_REVIEW", "BELOW_TARGET", "BUDGET_EXHAUSTED", "FAILED", "CANCELLED", "STAGNATED", "PAUSED")


def same(read, answer):
    """Whether a reading matches the answer: numbers to the cent, text ignoring case and spacing."""
    if isinstance(answer, list):
        return (
            isinstance(read, list)
            and len(read) == len(answer)
            and all(same(a, b) for a, b in zip(read, answer, strict=True))
        )
    if isinstance(answer, dict):
        return isinstance(read, dict) and all(same(read.get(field), value) for field, value in answer.items())
    if isinstance(answer, (int, float)) and not isinstance(answer, bool):
        try:
            return abs(float(read) - float(answer)) < 0.005
        except (TypeError, ValueError):
            return False
    return " ".join(str(read).split()).casefold() == " ".join(str(answer).split()).casefold()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", action="append", choices=list(REQUESTS), help="build only this agent (repeatable)")
    parser.add_argument("--documents-only", action="store_true")
    options = parser.parse_args()
    write()
    if options.documents_only:
        return
    kinds = options.only or list(REQUESTS)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    answers = json.loads((DATA / "answers.json").read_text())

    with httpx.Client(base_url=os.environ.get("FACTORY_API", "http://127.0.0.1:8000"), timeout=900) as api:

        def call(method, path, **request):
            response = api.request(method, path, **request)
            if response.status_code >= 400:
                raise SystemExit(f"{method} {path} answered {response.status_code}: {response.text[:500]}")
            return response.json() if response.content else None

        builder = "Bearer " + call("POST", "/auth/demo")["token"]
        api.headers["Authorization"] = builder
        projects = call("GET", "/projects", params={"limit": 200})["items"]
        project = next((item for item in projects if item["name"] == PROJECT), None) or call(
            "POST",
            "/projects",
            json={"name": PROJECT, "description": "Agents for a restaurant group's paperwork, on sample documents"},
        )
        for kind in kinds:
            entry = state.setdefault(kind, {})
            if entry.get("deployment_id"):
                print(f"{kind}: already deployed (held back {entry.get('held_back')})")
                continue
            if not entry.get("agent_id"):
                agent = call(
                    "POST",
                    "/agents",
                    json={"project_id": project["id"], "request": REQUESTS[kind], "minimum_score": TARGET},
                )
                call(
                    "POST",
                    f"/agents/{agent['id']}/context",
                    json={"name": f"{kind}.md", "text": (DATA / "procedures" / f"{kind}.md").read_text()},
                )
                with open(DATA / "examples" / f"{kind}-examples.zip", "rb") as archive:
                    call(
                        "POST",
                        f"/agents/{agent['id']}/datasets/archive",
                        files={"file": (f"{kind}-examples.zip", archive, "application/zip")},
                        data={"name": f"{LABELS[kind]} examples", "development": 8, "selection": 6, "validation": 10},
                    )
                entry.update(agent_id=agent["id"], name=agent["name"])
                STATE.write_text(json.dumps(state, indent=1) + "\n")
            if not entry.get("build_id"):
                build = call(
                    "POST",
                    f"/agents/{entry['agent_id']}/builds",
                    json={"max_iterations": ROUNDS, "max_cost": MAX_COST, "target_score": TARGET},
                )
                entry["build_id"] = build["id"]
                STATE.write_text(json.dumps(state, indent=1) + "\n")
            started = time.time()
            while True:
                job = call("GET", f"/builds/{entry['build_id']}")
                if job["state"] in DONE:
                    break
                print(
                    f"{kind}: {job['state']}, round {job['iteration']}, ${job['spent']:.3f}, {time.time() - started:.0f}s",
                    flush=True,
                )
                time.sleep(20)
            held_back = (job["checkpoint"].get("validation_scorecard") or {}).get("score")
            entry.update(
                state=job["state"],
                held_back=held_back,
                cost=round(job["spent"] + job.get("factory_observed_cost", 0), 4),
            )
            STATE.write_text(json.dumps(state, indent=1) + "\n")
            print(f"{kind}: build ended {job['state']}, held-back score {held_back}, ${entry['cost']}")
            if job["state"] != "READY_FOR_REVIEW":
                print(f"{kind}: not approved, because it did not meet its target. It is left out of the workspace.")
                continue
            version = call("GET", f"/agents/{entry['agent_id']}")["best_version_id"]
            call("POST", f"/versions/{version}/approve")
            deployment = call("POST", f"/agents/{entry['agent_id']}/deployments", json={"version_id": version})
            entry.update(version_id=version, deployment_id=deployment["id"])
            STATE.write_text(json.dumps(state, indent=1) + "\n")

        customer = next((item for item in call("GET", "/customers")["items"] if item["name"] == GROUP), None)
        if customer is None:
            raise SystemExit(f"{GROUP} has no workspace yet. Run bash demo/operations/seed.sh first.")
        for kind in REQUESTS:
            entry = state.get(kind, {})
            placed = next((item for item in customer["operations"] if item["name"] == LABELS[kind]), None)
            if entry.get("deployment_id") and placed is None:
                customer = call(
                    "POST",
                    f"/customers/{customer['id']}/operations",
                    json={"deployment_id": entry["deployment_id"], "name": LABELS[kind]},
                )
            elif placed and entry.get("version_id") and placed["source"].get("version_id") != entry["version_id"]:
                # A newer build of this agent: it replaces the one at work, and what that one read is read again.
                call(
                    "POST",
                    f"/customers/{customer['id']}/operations/{placed['id']}/upgrade",
                    json={"deployment_id": entry["deployment_id"]},
                )
                print(f"{kind}: the agent at work was replaced by the new build")
        api.headers["Authorization"] = (
            "Bearer " + call("POST", "/auth/switch-organization", json={"org_id": customer["id"]})["token"]
        )
        operations = {item["name"]: item for item in call("GET", "/portal/me")["operations"]}
        for kind in kinds:
            operation = operations.get(LABELS[kind])
            if operation is None:
                continue
            right = held = 0
            files = sorted((DATA / "baseline" / kind).glob("*.pdf"))
            for position, path in enumerate(files, 1):
                started = time.time()
                made = call(
                    "POST",
                    f"/portal/operations/{operation['id']}/documents",
                    files={"file": (path.name, path.read_bytes(), "application/pdf")},
                )
                ok = made["status"] == "processed" and same(made.get("answer"), answers[f"baseline/{kind}/{path.name}"])
                right += ok
                held += made.get("stage") == "review"
                note = (
                    ""
                    if ok
                    else f"  DIFFERS: {made.get('error') or [item['message'] for item in made.get('exception_list', [])] or 'reading'}"
                )
                print(
                    f"{kind} {position}/{len(files)} {path.name}: {made['status']} {made.get('stage')} {time.time() - started:.0f}s{note}",
                    flush=True,
                )
            entry = state.setdefault(kind, {})
            entry.update(baseline=len(files), baseline_right=right, baseline_held=held)
            STATE.write_text(json.dumps(state, indent=1) + "\n")
            print(f"{kind}: {right} of {len(files)} read exactly as the answers have them; {held} held for a person")
    print(
        json.dumps(
            {
                kind: {
                    key: value
                    for key, value in entry.items()
                    if key in ("state", "held_back", "cost", "baseline", "baseline_right", "baseline_held")
                }
                for kind, entry in state.items()
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
