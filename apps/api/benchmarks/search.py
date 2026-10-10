"""Benchmark of the builder's search loop on the real engine.

Two modes.

Simulated (default, needs no provider): a seeded proposer draws imperfect ideas from a fixed pool that
contains helpful, useless and harmful changes. Every arm sees the same kind of proposer, so differences
come from the loop: whether it remembers what it tried, and whether it screens several candidates per
round. Agent execution and grading are the real ones, on the order suite's authored cases. This measures
search mechanics. It says nothing about whether a model writes good proposals.

Live (--live, needs OPENAI_API_KEY and EXECUTION_MODE=live): the real optimizer, one-shot against the
tool-using harness, on the same task. This is the measurement that tells you whether the builder helps.

Run from apps/api:
    .venv/bin/python -m benchmarks.search --seeds 30
    EXECUTION_MODE=live OPENAI_API_KEY=... .venv/bin/python -m benchmarks.search --live --seeds 3
"""

import argparse
import asyncio
import json
import random
import statistics
import sys
import tempfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from factory import workflow
from factory.builder import design, persist_version
from factory.config import settings
from factory.connectors import discover_connection
from factory.db import Base, make_engine
from factory.fixtures import seed_business, seed_suite
from factory.models import (
    AgentRecord,
    BuildIteration,
    Connection,
    EvaluationResult,
    EvaluationRun,
    Membership,
    Organization,
    Project,
    User,
)
from factory.schemas import Budget

# Ideas a proposer may have. Two fix real defects, two do nothing, three do harm.
POOL = [
    ("Resolve customer aliases", {"resolve_aliases": True}),
    ("Match close typos", {"fuzzy_match": True}),
    ("Adjust the quote margin", {"margin": 0.3}),
    ("Reword the instructions", {}),
    ("Skip the stock check", {"check_inventory": False}),
    ("Resolve aliases and skip the stock check", {"resolve_aliases": True, "check_inventory": False}),
    ("Match typos and skip the stock check", {"fuzzy_match": True, "check_inventory": False}),
]

SIMULATED_ARMS = {
    "single, no memory": {"budget": {"candidates_per_round": 1}, "memory": False},
    "single, with memory": {"budget": {"candidates_per_round": 1}, "memory": True},
    "three screened, with memory": {"budget": {"candidates_per_round": 3}, "memory": True},
}
LIVE_ARMS = {
    "one-shot optimizer": {"budget": {"candidates_per_round": 1, "investigator_turns": 0}},
    "harness (investigate, 3 screened)": {"budget": {"candidates_per_round": 3, "investigator_turns": 6}},
}
LIMITS = {"max_iterations": 12, "stagnation_limit": 8, "max_seconds": 3600}


def simulated_proposer(seed, memory, log):
    rng = random.Random(seed)

    async def propose(spec, development_failures, history=None, **kwargs):
        tried = {entry.get("hypothesis") for entry in (history or [])} if memory else set()
        options = [idea for idea in POOL if idea[0] not in tried] or POOL
        name, rules = rng.choice(options)
        log.append(name)
        candidate = spec.model_copy(deep=True)
        candidate.rules.update(rules)
        if not rules:
            candidate.instructions += "\nBe careful."
        return candidate, name

    return propose


def new_workspace(directory):
    engine = make_engine(f"sqlite:///{directory}/benchmark.db")
    Base.metadata.create_all(engine)
    return engine


async def seed(db):
    org = Organization(name="Benchmark")
    user = User(email="benchmark@example.invalid", password_hash="unused")
    db.add_all([org, user])
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="admin"))
    project = Project(org_id=org.id, name="Benchmark")
    connection = Connection(
        org_id=org.id,
        name="Fictional ERP",
        kind="fixture",
        permissions={"read": True, "write": True},
        status="connected",
    )
    db.add_all([project, connection])
    db.flush()
    await discover_connection(db, connection)
    seed_business(db, org.id)
    agent = AgentRecord(
        org_id=org.id,
        project_id=project.id,
        name="Orders",
        request="Process restaurant orders safely",
        template="orders",
    )
    db.add(agent)
    db.flush()
    # The baseline deliberately lacks alias and typo handling: those are the injected defects.
    persist_version(db, agent, await design(db, agent, [connection.id], model_backed=False))
    seed_suite(db, agent)
    db.commit()
    return agent


async def run_build(budget, proposer=None, max_ticks=20000, skip_architect=False):
    """One build to a terminal state on a fresh database. Returns what it cost and what it achieved."""
    original = workflow.optimize
    with tempfile.TemporaryDirectory() as directory:
        engine = new_workspace(directory)
        try:
            with sessionmaker(engine, expire_on_commit=False)() as db:
                agent = await seed(db)
                if proposer:
                    workflow.optimize = proposer
                job = workflow.new_job(db, agent, Budget(**{**LIMITS, **budget}))
                if skip_architect:
                    # Both arms start from the same authored baseline so only the optimizer differs.
                    job.state = "BUILDING"
                for _ in range(max_ticks):
                    await workflow.advance(db, job)
                    db.commit()
                    if job.state in workflow.TERMINAL:
                        break
                validation = job.checkpoint.get("validation_scorecard") or {}
                best = job.checkpoint.get("best_scorecard") or {}
                return {
                    "state": job.state,
                    "succeeded": job.state == "READY_FOR_REVIEW",
                    "full_evaluations": db.scalar(
                        select(func.count()).select_from(BuildIteration).where(BuildIteration.job_id == job.id)
                    ),
                    "trials": db.scalar(select(func.count()).select_from(EvaluationResult)),
                    "screen_runs": db.scalar(
                        select(func.count()).select_from(EvaluationRun).where(EvaluationRun.status == "screen")
                    ),
                    "best_score": best.get("score"),
                    "held_out_score": validation.get("score"),
                    "cost": job.spent,
                    "stop_reason": job.checkpoint.get("stop_reason"),
                    "error": job.error,
                    "baseline_score": (job.checkpoint.get("attempts") or [{}])[0].get("score"),
                    # What was tried and how it measured: the evidence behind the summary row.
                    "attempts": job.checkpoint.get("attempts", []),
                }
        finally:
            workflow.optimize = original
            engine.dispose()


def summarize(name, runs, proposals=None):
    done = [run for run in runs if run["succeeded"]]

    def mean(key, rows):
        values = [row[key] for row in rows if row[key] is not None]
        return round(statistics.fmean(values), 2) if values else None

    return {
        "arm": name,
        "builds": len(runs),
        "success_rate": round(len(done) / len(runs), 2),
        "mean_full_evaluations": mean("full_evaluations", runs),
        "mean_trials": mean("trials", runs),
        "mean_trials_when_successful": mean("trials", done),
        "mean_proposals": round(statistics.fmean(proposals), 2) if proposals else None,
        "mean_held_out_score": mean("held_out_score", done),
        "mean_cost": mean("cost", runs),
        "mean_baseline_score": mean("baseline_score", runs),
        "mean_best_score": mean("best_score", runs),
    }


async def simulated(seeds):
    report = []
    for name, arm in SIMULATED_ARMS.items():
        runs, proposals = [], []
        for seed_value in range(seeds):
            log = []
            runs.append(await run_build(arm["budget"], simulated_proposer(seed_value, arm["memory"], log)))
            proposals.append(len(log))
        report.append(summarize(name, runs, proposals))
    return report


async def live(seeds, max_cost, max_iterations=5):
    if settings().execution_mode != "live" or not settings().openai_api_key:
        raise SystemExit(
            "The live benchmark needs a real provider: set EXECUTION_MODE=live and OPENAI_API_KEY. "
            "No key is configured, so only the simulated search-mechanics benchmark can run."
        )
    report = []
    for name, arm in LIVE_ARMS.items():
        budget = {**arm["budget"], "max_cost": max_cost, "max_iterations": max_iterations, "stagnation_limit": 3}
        runs = []
        for index in range(seeds):
            runs.append(await run_build(budget, skip_architect=True))
            print(f"[{name}] build {index + 1}: {runs[-1]['state']} best={runs[-1]['best_score']}", flush=True)
        report.append({**summarize(name, runs), "runs": runs})
    return report


def table(report):
    columns = [
        ("arm", "Arm"),
        ("success_rate", "Reached target"),
        ("mean_full_evaluations", "Full evals"),
        ("mean_trials", "Trials"),
        ("mean_proposals", "Proposals"),
        ("mean_baseline_score", "Baseline"),
        ("mean_best_score", "Best"),
        ("mean_held_out_score", "Held-out"),
        ("mean_cost", "Cost"),
    ]
    rows = [[label for _, label in columns]] + [
        ["-" if row[key] is None else str(row[key]) for key, _ in columns] for row in report
    ]
    widths = [max(len(row[index]) for row in rows) for index in range(len(columns))]
    return "\n".join("  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)) for row in rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-cost", type=float, default=5.0)
    parser.add_argument("--max-iterations", type=int, default=5, help="full evaluations per live build")
    parser.add_argument("--json", type=Path)
    arguments = parser.parse_args(argv)
    report = asyncio.run(
        live(arguments.seeds, arguments.max_cost, arguments.max_iterations)
        if arguments.live
        else simulated(arguments.seeds)
    )
    mode = "live" if arguments.live else "simulated proposer (search mechanics only)"
    print(f"Mode: {mode}. Builds per arm: {arguments.seeds}.\n")
    print(table(report))
    if arguments.json:
        arguments.json.write_text(json.dumps({"mode": mode, "seeds": arguments.seeds, "arms": report}, indent=2))
    return report


if __name__ == "__main__":
    main(sys.argv[1:])
