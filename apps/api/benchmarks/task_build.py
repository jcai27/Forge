"""Build one agent from a task, example data and optional business documents, and report how good it is.

This is the whole product path on a real model: the request goes through the API, the data is fetched
and split by the platform, the worker loop designs, evaluates and improves the agent, and the result is
judged on rows the builder never saw. Nothing here is specific to one task.

Needs a real provider. Run from apps/api with the key in the environment:

    EXECUTION_MODE=live .venv/bin/python -m benchmarks.task_build \\
        --task "Route each customer message to the right banking support queue." \\
        --data https://example.org/tickets.csv --development 20 --validation 20 --max-cost 1

Every model call spends money. --max-cost is the ceiling for the build; --baseline adds one more pass
over the held-out rows to measure the first version for comparison.
"""

import argparse
import asyncio
import contextlib
import json
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from factory import workflow
from factory.api import app, limits
from factory.config import settings
from factory.db import Base, get_db, make_engine
from factory.evaluation import evaluate_suite
from factory.models import (
    AgentRecord,
    AgentVersion,
    BuildIteration,
    BuildJob,
    Dataset,
    EvaluationSuite,
    ExecutionEvent,
    Membership,
    Organization,
    Project,
    UsageRecord,
    User,
)
from factory.security import token_for


def setup(db):
    org = Organization(name="Task build")
    user = User(email="task-build@example.invalid", password_hash="unused")
    db.add_all([org, user])
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="admin"))
    project = Project(org_id=org.id, name="Task build")
    db.add(project)
    db.commit()
    return org, user, project


def required(response, what):
    if response.status_code >= 400:
        raise SystemExit(f"{what} was refused ({response.status_code}): {response.json()['error']['message']}")
    return response.json()


async def drive(sessions, job_id, max_ticks):
    """Run the real worker until the build ends, printing each change of stage."""
    seen = None
    for _ in range(max_ticks):
        with sessions() as db:
            job = db.get(BuildJob, job_id)
            label = (job.state, job.iteration)
            if label != seen:
                seen = label
                print(
                    f"  {job.state.lower().replace('_', ' ')}  round {job.iteration}  spent ${job.spent:.3f}",
                    flush=True,
                )
            if job.state in workflow.INACTIVE:
                return job.state
        if not await workflow.worker_tick(sessions):
            await asyncio.sleep(0.2)
    return seen[0]


def usage_by_role(db, job_id):
    rows = db.execute(
        select(
            UsageRecord.role,
            func.count(),
            func.sum(UsageRecord.input_tokens),
            func.sum(UsageRecord.cached_tokens),
            func.sum(UsageRecord.output_tokens),
            func.sum(UsageRecord.cost),
            func.sum(UsageRecord.reserved_cost),
        )
        .where(UsageRecord.job_id == job_id)
        .group_by(UsageRecord.role)
    ).all()
    return {
        role: {
            "calls": calls,
            "input_tokens": sent or 0,
            "of_which_cached": cached or 0,
            "output_tokens": received or 0,
            "cost_usd": round(cost or 0, 4),
            "unresolved_usd": round(reserved or 0, 4),
        }
        for role, calls, sent, cached, received, cost, reserved in rows
    }


def part(card, split):
    rows = card["splits"].get(split)
    return f"{rows['passed']} of {rows['total']}" if rows else None


def summary(card):
    return (
        None
        if not card
        else {
            "passed": card["passed"],
            "total": card["total"],
            "score": round(card["score"], 4),
            "interval_95": [round(v, 3) for v in card["confidence_interval_95"]],
        }
    )


def start(arguments, org, user, project):
    """Create the agent, attach its documents and data, and start the build, all through the API."""
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
        agent = required(
            client.post(
                "/agents", json={"project_id": project.id, "request": arguments.task, "minimum_score": arguments.target}
            ),
            "The agent",
        )
        for path in arguments.context or []:
            required(
                client.post(f"/agents/{agent['id']}/context", json={"name": path.name, "text": path.read_text()}),
                f"The document {path.name}",
            )
        source = (
            {"url": arguments.data}
            if arguments.data.startswith("https://")
            else {"content": Path(arguments.data).read_text()}
        )
        dataset = required(
            client.post(
                f"/agents/{agent['id']}/datasets",
                json={
                    "name": arguments.name,
                    **source,
                    "development": arguments.development,
                    **({} if arguments.selection is None else {"selection": arguments.selection}),
                    "validation": arguments.validation,
                },
            ),
            "The dataset",
        )
        profile = dataset["profile"]
        print(
            f"Data: {profile['rows']} rows, {profile['splits']['development']} to build from, {profile['splits']['selection']} to check changes, {profile['splits']['validation']} held back, answers { ({k: len(v) for k, v in profile['answers'].items()}) }",
            flush=True,
        )
        budget = {
            "max_cost": arguments.max_cost,
            "max_iterations": arguments.max_iterations,
            "max_seconds": arguments.max_seconds,
            "target_score": arguments.target,
            "stagnation_limit": arguments.stagnation,
            "candidates_per_round": arguments.candidates,
            "investigator_turns": arguments.investigator_turns,
        }
        job = required(client.post(f"/agents/{agent['id']}/builds", json=budget), "The build")
    return agent, profile, job


async def run(arguments):
    config = settings()
    if config.execution_mode != "live" or not config.openai_api_key:
        raise SystemExit("This needs a real provider: set EXECUTION_MODE=live and OPENAI_API_KEY.")
    if arguments.model:
        config.openai_model = arguments.model
    if arguments.builder_model:
        config.builder_model = arguments.builder_model
    started = time.monotonic()
    with contextlib.ExitStack() as stack:
        # With --state the database is kept, so a run that was stopped, or that paused because the
        # provider could not be reached, picks up where it left off when the same command is run again.
        directory = arguments.state or stack.enter_context(tempfile.TemporaryDirectory())
        Path(directory).mkdir(parents=True, exist_ok=True)
        engine = make_engine(f"sqlite:///{Path(directory).resolve()}/task.db")
        Base.metadata.create_all(engine)
        sessions = sessionmaker(engine, expire_on_commit=False)
        with sessions() as db:
            earlier = db.scalar(select(BuildJob).order_by(BuildJob.created_at.desc()))
            resumed = earlier is not None
            if resumed:
                if earlier.state == "PAUSED":
                    workflow.control(db, earlier, "resume")
                dataset_row = db.scalar(select(Dataset).where(Dataset.agent_id == earlier.agent_id))
                job, agent, profile = {"id": earlier.id}, {"id": earlier.agent_id}, dataset_row.profile
                org = db.get(Organization, earlier.org_id)
                db.commit()
                print(f"Resuming the build in {directory} from {earlier.state.lower().replace('_', ' ')}", flush=True)

        def session():
            with sessions() as db:
                yield db

        app.dependency_overrides[get_db] = session
        limits.clear()
        try:
            if not resumed:
                with sessions() as db:
                    org, user, project = setup(db)
                agent, profile, job = start(arguments, org, user, project)
            print(
                f"Build: agent model {config.openai_model}, builder model {config.builder_model or config.openai_model}",
                flush=True,
            )
            state = await drive(sessions, job["id"], arguments.max_ticks)

            with sessions() as db:
                job = db.get(BuildJob, job["id"])
                record = db.get(AgentRecord, agent["id"])
                versions = {v.id: v for v in db.scalars(select(AgentVersion).where(AgentVersion.agent_id == record.id))}
                rounds = [
                    {
                        "round": row.number,
                        "version": versions[row.version_id].number,
                        "read_by_builder": part(row.scorecard, "development"),
                        "unseen": part(row.scorecard, "selection"),
                        "kept": row.promoted,
                        "hypothesis": versions[row.version_id].hypothesis[:240],
                    }
                    for row in db.scalars(
                        select(BuildIteration).where(BuildIteration.job_id == job.id).order_by(BuildIteration.number)
                    )
                ]
                best = versions.get(record.best_version_id)
                report = {
                    "task": arguments.task,
                    "state": state,
                    "stop_reason": job.checkpoint.get("stop_reason"),
                    "waiting": job.checkpoint.get("waiting_reason") if state in workflow.WAITING else None,
                    "error": job.error,
                    "data": {"rows": profile["rows"], "splits": profile["splits"], "dropped": profile["dropped"]},
                    "models": {"agent": config.openai_model, "builder": config.builder_model or config.openai_model},
                    "rounds": rounds,
                    "best_version": best.number if best else None,
                    "held_out": summary(job.checkpoint.get("validation_scorecard")),
                    "rejected_proposals": [
                        event.payload.get("reason")
                        for event in db.scalars(
                            select(ExecutionEvent).where(
                                ExecutionEvent.job_id == job.id, ExecutionEvent.kind == "proposal_rejected"
                            )
                        )
                    ],
                    "corrected_checks": [
                        event.payload.get("verifiers")
                        for event in db.scalars(
                            select(ExecutionEvent).where(
                                ExecutionEvent.job_id == job.id, ExecutionEvent.kind == "verifiers_contradicted"
                            )
                        )
                    ],
                }
                first = versions.get(
                    db.scalar(
                        select(BuildIteration.version_id)
                        .where(BuildIteration.job_id == job.id)
                        .order_by(BuildIteration.number)
                        .limit(1)
                    )
                    or ""
                )
                baseline_cost = 0.0
                if arguments.baseline and first is not None and best is not None and first.id != best.id:
                    # The first version the build measured, on the same held-out rows, for comparison.
                    suite = db.scalar(select(EvaluationSuite).where(EvaluationSuite.agent_id == record.id))
                    evaluation = await evaluate_suite(
                        db,
                        first,
                        suite,
                        ("validation",),
                        max_cost=arguments.max_cost,
                        max_seconds=arguments.max_seconds,
                    )
                    db.commit()
                    report["held_out_first_version"] = {"version": first.number, **summary(evaluation.scorecard)}
                    baseline_cost = evaluation.scorecard["cost"]
                elif first is not None and best is not None and first.id == best.id:
                    report["held_out_first_version"] = "the first version is the best version"
                priced = config.model_prices.get(config.openai_model)
                report["spend"] = {
                    "build_usd": round(job.spent, 4),
                    "baseline_pass_usd": round(baseline_cost, 4),
                    "by_role": usage_by_role(db, job.id),
                    "note": (
                        f"Priced at ${priced[0]:.2f} input and ${priced[1]:.2f} output per million tokens for "
                        f"{config.openai_model}; check the provider's bill."
                        if priced
                        else f"No price is configured for {config.openai_model}; a flat estimate was used."
                    ),
                }
                report["minutes"] = round((time.monotonic() - started) / 60, 1)
                if best is not None:
                    report["final_instructions"] = best.spec["instructions"]
                    report["final_bundle"] = {
                        "examples": len(best.spec.get("examples") or []),
                        "verifiers": len(best.spec.get("verifiers") or []),
                        "generated_tools": len(best.spec.get("generated_tools") or []),
                    }
                return report
        finally:
            app.dependency_overrides.clear()
            engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--task", required=True, help="what the agent is for, in plain words")
    parser.add_argument(
        "--data", required=True, help="a file, or a public https address, of examples with correct answers"
    )
    parser.add_argument("--name", default="Examples")
    parser.add_argument(
        "--context", type=Path, action="append", help="a text document about how the business operates; may be repeated"
    )
    parser.add_argument("--development", type=int, default=60)
    parser.add_argument(
        "--selection", type=int, help="rows each change is scored on, unread; default: as many as development"
    )
    parser.add_argument("--validation", type=int, default=60)
    parser.add_argument("--max-cost", type=float, default=2.0)
    parser.add_argument("--max-iterations", type=int, default=6)
    parser.add_argument("--max-seconds", type=int, default=7200)
    parser.add_argument("--target", type=float, default=0.95)
    parser.add_argument("--stagnation", type=int, default=3)
    parser.add_argument("--candidates", type=int, default=1)
    parser.add_argument("--investigator-turns", type=int, default=6)
    parser.add_argument("--model", help="model the agent runs on; defaults to OPENAI_MODEL")
    parser.add_argument("--builder-model", help="model the builder runs on; defaults to BUILDER_MODEL")
    parser.add_argument("--baseline", action="store_true", help="also measure the first version on the held-out rows")
    parser.add_argument("--max-ticks", type=int, default=200000)
    parser.add_argument(
        "--state", help="a directory to keep the run in, so it can be resumed by running the same command again"
    )
    parser.add_argument("--json", type=Path)
    arguments = parser.parse_args(argv)
    report = asyncio.run(run(arguments))
    print(json.dumps(report, indent=2))
    if arguments.json:
        arguments.json.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    sys.exit(main())
