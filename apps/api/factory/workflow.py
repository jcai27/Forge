"""Checkpointed workflow: each worker tick persists one stage or one evaluation trial."""

from collections import Counter
from copy import deepcopy
from datetime import UTC, timedelta

from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError
from sqlalchemy import select, update

from factory.builder import design, design_tests, mutable_view, optimize, persist_version
from factory.config import settings
from factory.connectors import check_connection
from factory.db import SessionLocal, now, uid
from factory.evaluation import can_promote, development_evidence, evaluate_case, passing_examples, scorecard
from factory.models import (
    AgentRecord,
    AgentVersion,
    BuildIteration,
    BuildJob,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationSuite,
    ExecutionRun,
    UsageRecord,
)
from factory.optimizer_tools import Investigation
from factory.provider_accounting import BuildInterrupted, FactoryBudgetHooks, recover_reservations
from factory.release import playbook
from factory.research import OutboundScreen, tenant_markers
from factory.runtime import BudgetExceeded, emit
from factory.schemas import AgentSpec, Budget
from factory.security import known_secret_values

TERMINAL = {"READY_FOR_REVIEW", "DEPLOYED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"}
INACTIVE = TERMINAL | {"PAUSED", "WAITING_FOR_APPROVAL"}


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def new_job(db, agent, budget):
    active = db.scalar(select(BuildJob).where(BuildJob.agent_id == agent.id, BuildJob.state.not_in(TERMINAL)))
    if active:
        raise ValueError("Agent already has an active or paused build")
    version = db.scalar(
        select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.number.desc())
    )
    if not version:
        raise ValueError("Create an agent version before building")
    job = BuildJob(
        org_id=agent.org_id,
        agent_id=agent.id,
        budget=budget.model_dump(),
        checkpoint={"version_id": version.id, "stagnation": 0},
    )
    db.add(job)
    db.flush()
    emit(db, job.org_id, "build_created", {"budget": job.budget, "state": job.state}, job_id=job.id)
    return job


def transition(db, job, state, checkpoint=None):
    job.state = state
    if checkpoint is not None:
        # Always store a fresh object: an autoflush between two in-place edits of the same dict
        # would otherwise hide the second edit from change detection.
        job.checkpoint = deepcopy(checkpoint)
    emit(db, job.org_id, "build_state", {"state": state, "iteration": job.iteration, "spent": job.spent}, job_id=job.id)


def start_evaluation(db, job, version, suite, validation=False):
    evaluation = EvaluationRun(org_id=job.org_id, version_id=version.id, suite_id=suite.id)
    db.add(evaluation)
    db.flush()
    job.checkpoint = {**job.checkpoint, "evaluation_id": evaluation.id, "validation": validation}


def record_role_usage(db, job, role, usage):
    if not usage.get("accounted"):
        job.spent += usage.get("cost", 0)
        db.add(
            UsageRecord(
                org_id=job.org_id, job_id=job.id, role=role, tokens=usage.get("tokens", 0), cost=usage.get("cost", 0)
            )
        )
    emit(db, job.org_id, "factory_role_usage", {"role": role, **usage}, job_id=job.id)


# A proposal that breaks its contract is a rejected idea, not a failed build.
# A proposal that runs out of time is one too: the reservation is kept as uncertain, the build goes on.
REJECTED_PROPOSAL = (PermissionError, ValidationError, ModelBehaviorError, MaxTurnsExceeded, TimeoutError)

STRATEGIES = [
    "Make the smallest change to the instructions that fixes the most common development failure.",
    "Add or revise worked examples and tool usage notes that would prevent the observed failures.",
    "Add deterministic verifiers that catch the observed wrong outputs, and adjust a rule where one explains them.",
    "Propose a different explanation for the failures than earlier attempts did, and act on that.",
]


def record_attempt(checkpoint, attempt):
    checkpoint["attempts"] = [*checkpoint.get("attempts", []), attempt][-12:]


def screen_sets(db, suite, checkpoint, sample):
    """Development cases a candidate is screened on: the parent's failures plus a few it must not break.

    Only deterministically graded cases qualify; human-reviewed and rubric cases need the full evaluation.
    """
    rates = (checkpoint.get("best_scorecard") or {}).get("case_rates", {})
    failing, passing = [], []
    for case in db.scalars(
        select(EvaluationCase)
        .where(EvaluationCase.suite_id == suite.id, EvaluationCase.split == "development")
        .order_by(EvaluationCase.id)
    ):
        if case.source == "human" or case.rubric or case.id not in rates:
            continue
        passed, trials = rates[case.id]
        (failing if passed < trials else passing).append(case.id)
    return failing, passing[:sample]


async def run_next_trial(db, job, budget, elapsed, checkpoint, evaluation, version, cases):
    """Run one remaining (case, trial). Returns "ran", "done", "interrupted" or "stopped"."""
    completed = {
        (r.case_id, r.trial)
        for r in db.scalars(select(EvaluationResult).where(EvaluationResult.evaluation_run_id == evaluation.id))
    }
    remaining = [(case, trial) for case in cases for trial in range(case.trials) if (case.id, trial) not in completed]
    if not remaining:
        return "done"
    case, trial = remaining[0]
    try:
        result = await evaluate_case(
            db,
            evaluation,
            version,
            case,
            trial,
            max_cost=max(0, budget.max_cost - job.spent),
            max_seconds=max(0, budget.max_seconds - elapsed),
            job=job,
        )
    except BuildInterrupted:
        return "interrupted"
    run = db.get(ExecutionRun, result.execution_id)
    job.spent += max(0, run.metrics.get("cost", 0) - run.metrics.get("build_accounted_cost", 0))
    run.metrics = {**run.metrics, "build_accounted_cost": run.metrics.get("cost", 0)}
    if run.error == "BudgetExceeded":
        transition(
            db, job, "BUDGET_EXHAUSTED", {**checkpoint, "stop_reason": "insufficient_budget_before_provider_call"}
        )
        return "stopped"
    emit(
        db,
        job.org_id,
        "evaluation_case",
        {
            "evaluation_id": evaluation.id,
            "case_id": case.id,
            "name": case.name,
            "split": case.split,
            "trial": trial,
            "passed": result.passed,
            "completed": len(completed) + 1,
            "total": len(completed) + len(remaining),
            "failures": result.failures,
            "screen": evaluation.status == "screening",
        },
        job_id=job.id,
    )
    return "ran"


def next_round_or_stop(db, job, budget, checkpoint):
    """After a round with no promotion: stop at the limits, otherwise propose again from the parent."""
    checkpoint.pop("round", None)
    if job.iteration >= budget.max_iterations or checkpoint.get("stagnation", 0) >= budget.stagnation_limit:
        transition(db, job, "BUDGET_EXHAUSTED", {**checkpoint, "stop_reason": "iterations_or_stagnation_limit"})
    else:
        transition(db, job, "OPTIMIZING", checkpoint)


async def advance(db, job):
    if job.state in INACTIVE:
        return
    budget = Budget.model_validate(job.budget)
    checkpoint = dict(job.checkpoint)
    elapsed = (now() - utc(job.created_at)).total_seconds()
    if job.spent > budget.max_cost or elapsed > budget.max_seconds:
        transition(db, job, "BUDGET_EXHAUSTED", {**checkpoint, "stop_reason": "cost_or_elapsed_budget"})
        return
    agent = db.get(AgentRecord, job.agent_id)
    version = db.get(AgentVersion, checkpoint["version_id"])
    suite = db.scalar(select(EvaluationSuite).where(EvaluationSuite.agent_id == agent.id))
    if job.state == "DRAFT":
        transition(db, job, "DISCOVERING")
    elif job.state == "DISCOVERING":
        spec = AgentSpec.model_validate(version.spec)
        for connection_id in spec.connection_ids:
            check_connection(db, job.org_id, connection_id)
        if not spec.tools:
            raise ValueError("No authorized tools are available")
        emit(
            db,
            job.org_id,
            "integration_discovery",
            {"connections": spec.connection_ids, "tools": spec.tools},
            job_id=job.id,
        )
        transition(db, job, "DESIGNING")
    elif job.state == "DESIGNING":
        if settings().execution_mode == "live":
            usage = {}
            try:
                spec = await design(
                    db,
                    agent,
                    version.spec["connection_ids"],
                    max_cost=max(0, budget.max_cost - job.spent),
                    max_seconds=min(120, max(0, budget.max_seconds - elapsed)),
                    usage=usage,
                    hooks=FactoryBudgetHooks(max(0, budget.max_cost - job.spent), db, job, "requirements_architect"),
                )
                # User quality policy and resource ceilings remain authoritative.
                spec.quality_policy = AgentSpec.model_validate(version.spec).quality_policy
                version = persist_version(db, agent, spec, "Background requirements analysis and architecture")
                checkpoint["version_id"] = version.id
                job.checkpoint = deepcopy(checkpoint)
                agent.name = spec.name
            except BuildInterrupted:
                return
            except Exception as error:
                record_role_usage(db, job, "requirements_architect", usage)
                job.error = type(error).__name__
                transition(
                    db,
                    job,
                    "BUDGET_EXHAUSTED" if isinstance(error, BudgetExceeded) else "FAILED",
                )
                return
            record_role_usage(db, job, "requirements_architect", usage)
        emit(
            db,
            job.org_id,
            "requirements_analyzed",
            {
                "objective": agent.request,
                "template": agent.template,
                "side_effect_policy": "human_approval",
                "required_systems": version.spec["connection_ids"],
                "requirements": version.spec.get("requirements"),
            },
            job_id=job.id,
        )
        transition(db, job, "BUILDING")
    elif job.state == "BUILDING":
        if not suite or not db.scalar(select(EvaluationCase).where(EvaluationCase.suite_id == suite.id).limit(1)):
            if settings().execution_mode == "live" and not checkpoint.get("test_proposals"):
                usage = {}
                try:
                    proposal = await design_tests(
                        db,
                        version,
                        max_cost=max(0, budget.max_cost - job.spent),
                        max_seconds=min(60, max(0, budget.max_seconds - elapsed)),
                        usage=usage,
                        hooks=FactoryBudgetHooks(
                            max(0, budget.max_cost - job.spent),
                            db,
                            job,
                            "test_designer",
                            max_seconds=min(60, max(0, budget.max_seconds - elapsed)),
                        ),
                    )
                    checkpoint["test_proposals"] = proposal.model_dump()
                except BuildInterrupted:
                    return
                except Exception as error:
                    record_role_usage(db, job, "test_designer", usage)
                    job.error = type(error).__name__
                    transition(db, job, "BUDGET_EXHAUSTED" if isinstance(error, BudgetExceeded) else "FAILED")
                    return
                record_role_usage(db, job, "test_designer", usage)
            transition(
                db,
                job,
                "WAITING_FOR_APPROVAL",
                {
                    **checkpoint,
                    "waiting_reason": "Review and correct proposed cases, or import authored cases, before evidence-based optimization",
                },
            )
            return
        start_evaluation(db, job, version, suite)
        transition(db, job, "TESTING")
    elif job.state in ("TESTING", "RETESTING"):
        evaluation = db.get(EvaluationRun, checkpoint["evaluation_id"])
        splits = ["validation"] if checkpoint.get("validation") else ["development", "regression"]
        cases = list(
            db.scalars(
                select(EvaluationCase)
                .where(EvaluationCase.suite_id == suite.id, EvaluationCase.split.in_(splits))
                .order_by(EvaluationCase.id)
            )
        )
        outcome = await run_next_trial(db, job, budget, elapsed, checkpoint, evaluation, version, cases)
        if outcome in ("interrupted", "stopped"):
            return
        if outcome == "done":
            evaluation.scorecard = scorecard(db, evaluation)
            evaluation.status = "completed"
            if evaluation.scorecard.get("pending_reviews"):
                transition(
                    db,
                    job,
                    "WAITING_FOR_APPROVAL",
                    {
                        **checkpoint,
                        "resume_state": job.state,
                        "waiting_reason": "Pending human review or unavailable qualitative grading; review evidence before resuming",
                    },
                )
                return
            transition(db, job, "ANALYZING")
    elif job.state == "ANALYZING":
        evaluation = db.get(EvaluationRun, checkpoint["evaluation_id"])
        card = evaluation.scorecard
        policy = AgentSpec.model_validate(version.spec).quality_policy
        if checkpoint.get("validation"):
            if (
                card["distinct_cases"] >= policy.minimum_validation_cases
                and card["score"] >= max(budget.target_score, policy.minimum_score)
                and card["critical_failures"] == 0
                and card["metrics"].get("safety", 0) == 1
                and card["metrics"].get("approval_compliance", 0) == 1
                and card["mean_latency_ms"] <= policy.maximum_mean_latency_ms
                and card["cost"] <= policy.maximum_evaluation_cost
            ):
                transition(
                    db,
                    job,
                    "READY_FOR_REVIEW",
                    {**checkpoint, "validation_scorecard": card, "stop_reason": "target_achieved"},
                )
            else:
                transition(
                    db,
                    job,
                    "FAILED",
                    {
                        **checkpoint,
                        "validation_scorecard": card,
                        "stop_reason": "held_out_validation_failed_or_missing",
                    },
                )
            return
        evidence = development_evidence(db, evaluation)
        baseline = checkpoint.get("best_scorecard")
        policy = AgentSpec.model_validate(version.spec).quality_policy
        promoted = can_promote(card, baseline, policy.model_dump())
        diagnosis = {
            "development_failures": evidence,
            "categories": dict(
                Counter(check["category"] for failure in evidence for check in failure["failed_checks"])
            ),
            "hidden_validation_shared_with_optimizer": False,
        }
        job.iteration += 1
        db.add(
            BuildIteration(
                org_id=job.org_id,
                job_id=job.id,
                number=job.iteration,
                version_id=version.id,
                scorecard=card,
                diagnosis=diagnosis,
                promoted=promoted,
            )
        )
        # A lab notebook of what was tried, so the optimizer never repeats a rejected edit.
        names = card.get("case_names", {})
        lost = [
            names.get(key.split(":")[0], key)
            for key, passed in (baseline or {}).get("regression_outcomes", {}).items()
            if passed and not card.get("regression_outcomes", {}).get(key, False)
        ]
        attempt = {
            "iteration": job.iteration,
            "version_number": version.number,
            "hypothesis": version.hypothesis,
            "promoted": promoted,
            "score": card["score"],
            "graded_score": card.get("graded_score"),
            "baseline_score": baseline["score"] if baseline else None,
            "critical_failures": card["critical_failures"],
            "regressed_cases": sorted(set(lost))[:5],
            "development_failures": [failure["case"] for failure in evidence][:5],
        }
        checkpoint["attempts"] = [*checkpoint.get("attempts", []), attempt][-12:]
        if promoted:
            agent.best_version_id = version.id
            checkpoint.update(
                best_version_id=version.id,
                best_scorecard=card,
                best_diagnosis=diagnosis,
                best_passing=passing_examples(db, evaluation),
                best_evaluation_id=evaluation.id,
                stagnation=0,
            )
        else:
            checkpoint["stagnation"] = checkpoint.get("stagnation", 0) + 1
        checkpoint.update(diagnosis=diagnosis, last_diagnosis=diagnosis, last_scorecard=card)
        emit(
            db,
            job.org_id,
            "candidate_compared",
            {
                "version_id": version.id,
                "scorecard": card,
                "promoted": promoted,
                "baseline_score": baseline["score"] if baseline else None,
                "development_failures": len(evidence),
            },
            job_id=job.id,
        )
        if card["metrics"].get("safety", 0) < 1:
            transition(db, job, "FAILED", {**checkpoint, "stop_reason": "critical_safety_failure"})
        elif (
            checkpoint.get("best_scorecard", {}).get("score", 0) >= max(budget.target_score, policy.minimum_score)
            and checkpoint.get("best_scorecard", {}).get("distinct_cases", 0) >= policy.minimum_cases
        ):
            checkpoint["version_id"] = checkpoint["best_version_id"]
            checkpoint.pop("round", None)
            job.checkpoint = deepcopy(checkpoint)
            start_evaluation(db, job, db.get(AgentVersion, checkpoint["version_id"]), suite, validation=True)
            transition(db, job, "RETESTING")
        elif job.iteration >= budget.max_iterations or checkpoint["stagnation"] >= budget.stagnation_limit:
            checkpoint.pop("round", None)
            transition(db, job, "BUDGET_EXHAUSTED", {**checkpoint, "stop_reason": "iterations_or_stagnation_limit"})
        else:
            queue = list((checkpoint.get("round") or {}).get("queue", []))
            if not promoted and queue:
                # Another screened survivor of this round still deserves its full evaluation.
                survivor = db.get(AgentVersion, queue.pop(0))
                checkpoint["round"] = {**checkpoint["round"], "queue": queue}
                checkpoint["version_id"] = survivor.id
                job.checkpoint = deepcopy(checkpoint)
                start_evaluation(db, job, survivor, suite)
                transition(db, job, "RETESTING")
            else:
                checkpoint.pop("round", None)
                best_id = checkpoint.get("best_version_id")
                if best_id and best_id != version.id:
                    # Branch from the best-known version, never from a rejected candidate, and show the
                    # optimizer that version's failures rather than the rejected candidate's.
                    checkpoint["version_id"] = best_id
                    checkpoint["diagnosis"] = checkpoint.get("best_diagnosis", diagnosis)
                transition(db, job, "OPTIMIZING", checkpoint)
    elif job.state == "OPTIMIZING":
        # Never pass regression/validation answer records into optimizer context.
        round_ = dict(checkpoint.get("round") or {"parent_id": version.id, "candidates": [], "discarded": 0})
        candidates = [dict(item) for item in round_["candidates"]]
        index = len(candidates) + round_["discarded"]
        spec = AgentSpec.model_validate(version.spec)
        live = settings().execution_mode == "live"
        researching = live and bool(budget.investigator_turns) and settings().research_enabled
        ceiling = 60 if budget.investigator_turns == 0 else 240 if researching else 120
        seconds = min(ceiling, max(0, budget.max_seconds - elapsed))
        investigation = None
        if live and budget.investigator_turns:
            research = None
            if researching:
                evidence = [*checkpoint["diagnosis"]["development_failures"], *checkpoint.get("best_passing", [])]
                research = {
                    # Customer data seen by the builder must not leave in a question, query or URL.
                    "screen": OutboundScreen(known_secret_values(db, job.org_id), tenant_markers(evidence)),
                    "hooks": lambda: FactoryBudgetHooks(
                        max(0, budget.max_cost - job.spent), db, job, "researcher", max_seconds=seconds
                    ),
                    "on_usage": lambda used: record_role_usage(db, job, "researcher", used),
                    "max_calls": 2,
                    "max_seconds": 60,
                }
            investigation = Investigation(
                db,
                job,
                spec,
                checkpoint.get("best_evaluation_id") or checkpoint.get("evaluation_id"),
                checkpoint.get("attempts", []),
                research=research,
                proposals={"agent_id": agent.id, "max": 1},
            )
        usage, proposal, rejection = {}, None, None
        try:
            proposal = await optimize(
                spec,
                checkpoint["diagnosis"]["development_failures"],
                history=checkpoint.get("attempts", []),
                passing=checkpoint.get("best_passing", []),
                playbook=playbook(db, job.org_id, agent.template, exclude_agent_id=agent.id) if live else None,
                max_cost=max(0, budget.max_cost - job.spent),
                max_seconds=seconds,
                usage=usage,
                secret_values=known_secret_values(db, job.org_id),
                tools=investigation.tools() if investigation else None,
                max_turns=budget.investigator_turns + 2,
                strategy=STRATEGIES[index % len(STRATEGIES)] if budget.candidates_per_round > 1 else None,
                hooks=FactoryBudgetHooks(max(0, budget.max_cost - job.spent), db, job, "optimizer", max_seconds=seconds)
                if live
                else None,
            )
        except BuildInterrupted:
            return
        except REJECTED_PROPOSAL as error:
            rejection = type(error).__name__
        except Exception as error:
            record_role_usage(db, job, "optimizer", usage)
            job.error = type(error).__name__
            transition(db, job, "BUDGET_EXHAUSTED" if isinstance(error, BudgetExceeded) else "FAILED")
            return
        record_role_usage(db, job, "optimizer", usage)
        if investigation:
            emit(
                db,
                job.org_id,
                "optimizer_investigation",
                {
                    "calls": investigation.calls,
                    "denied": investigation.denied,
                    "research": investigation.research_log,
                    "connection_proposals": investigation.proposals,
                    "withheld_outbound": research["screen"].refused if research else [],
                },
                job_id=job.id,
            )
        new_version = None
        if proposal:
            candidate, hypothesis = proposal
            seen = {mutable_view(db.get(AgentVersion, item["version_id"]).spec) for item in candidates}
            duplicate = mutable_view(candidate) in seen or (index > 0 and mutable_view(candidate) == mutable_view(spec))
            if duplicate:
                rejection = "DuplicateProposal"
            else:
                try:
                    with db.begin_nested():
                        new_version = persist_version(db, agent, candidate, hypothesis)
                except (PermissionError, ValidationError, SchemaError, ValueError) as error:
                    rejection = type(error).__name__
        if new_version:
            candidates.append(
                {
                    "version_id": new_version.id,
                    "number": new_version.number,
                    "hypothesis": hypothesis,
                    "status": "proposed",
                    # Provenance: public pages that were in context when this candidate was written.
                    "research_sources": sorted(
                        {
                            url
                            for entry in (investigation.research_log if investigation else [])
                            for url in entry["sources"]
                        }
                    ),
                }
            )
            emit(
                db,
                job.org_id,
                "improvement_hypothesis",
                {
                    "hypothesis": hypothesis,
                    "version_id": new_version.id,
                    "number": new_version.number,
                    "research_sources": candidates[-1]["research_sources"],
                },
                job_id=job.id,
            )
        else:
            round_["discarded"] += 1
            record_attempt(
                checkpoint,
                {"iteration": job.iteration, "promoted": False, "rejected_before_evaluation": rejection},
            )
            emit(db, job.org_id, "proposal_rejected", {"reason": rejection}, job_id=job.id)
        round_["candidates"] = candidates
        checkpoint["round"] = round_
        exhausted = rejection == "DuplicateProposal" and not live  # the deterministic ladder has no more ideas
        if len(candidates) + round_["discarded"] < budget.candidates_per_round and not exhausted:
            job.checkpoint = deepcopy(checkpoint)
            return
        if not candidates:
            checkpoint["stagnation"] = checkpoint.get("stagnation", 0) + 1
            next_round_or_stop(db, job, budget, checkpoint)
            return
        failing, passing = screen_sets(db, suite, checkpoint, budget.screen_sample)
        if len(candidates) > 1 and failing:
            round_.update(screen_failing=failing, screen_passing=passing)
            checkpoint["round"] = round_
            transition(db, job, "SCREENING", checkpoint)
        else:
            first = db.get(AgentVersion, candidates[0]["version_id"])
            round_["queue"] = [item["version_id"] for item in candidates[1:]]
            checkpoint.update(round=round_, version_id=first.id)
            job.checkpoint = deepcopy(checkpoint)
            start_evaluation(db, job, first, suite)
            transition(db, job, "RETESTING")
    elif job.state == "SCREENING":
        round_ = dict(checkpoint["round"])
        candidates = [dict(item) for item in round_["candidates"]]
        current = next((item for item in candidates if item["status"] == "proposed"), None)
        if current is not None:
            candidate_version = db.get(AgentVersion, current["version_id"])
            if not current.get("screen_evaluation_id"):
                screen = EvaluationRun(
                    org_id=job.org_id, version_id=candidate_version.id, suite_id=suite.id, status="screening"
                )
                db.add(screen)
                db.flush()
                current["screen_evaluation_id"] = screen.id
            round_["candidates"] = candidates
            checkpoint["round"] = round_
            job.checkpoint = deepcopy(checkpoint)
            screen = db.get(EvaluationRun, current["screen_evaluation_id"])
            wanted = set(round_["screen_failing"]) | set(round_["screen_passing"])
            cases = list(
                db.scalars(
                    select(EvaluationCase)
                    .where(
                        EvaluationCase.suite_id == suite.id,
                        EvaluationCase.split == "development",
                        EvaluationCase.id.in_(wanted),
                    )
                    .order_by(EvaluationCase.id)
                )
            )
            outcome = await run_next_trial(db, job, budget, elapsed, checkpoint, screen, candidate_version, cases)
            if outcome != "done":
                return
            card = scorecard(db, screen)
            screen.scorecard, screen.status = card, "screen"
            parent = checkpoint["best_scorecard"]["case_rates"]

            def rate(rates, case_id):
                passed, trials = rates.get(case_id, [0, 1])
                return passed / trials

            fixed = sum(rate(card["case_rates"], c) > rate(parent, c) for c in wanted)
            broken = sum(rate(card["case_rates"], c) < rate(parent, c) for c in wanted)
            survived = (
                fixed > 0 and broken == 0 and not card["critical_failures"] and card["metrics"].get("safety", 0) == 1
            )
            current.update(
                status="survived" if survived else "pruned",
                screen={"fixed": fixed, "broken": broken, "graded_score": card["graded_score"]},
            )
            emit(
                db,
                job.org_id,
                "candidate_screened",
                {"version_id": current["version_id"], "survived": survived, **current["screen"]},
                job_id=job.id,
            )
            if not survived:
                record_attempt(
                    checkpoint,
                    {
                        "iteration": job.iteration,
                        "version_number": current["number"],
                        "hypothesis": current["hypothesis"],
                        "promoted": False,
                        "pruned_in_screen": True,
                        "fixed_cases": fixed,
                        "broken_cases": broken,
                    },
                )
            round_["candidates"] = candidates
            checkpoint["round"] = round_
            job.checkpoint = deepcopy(checkpoint)
            if any(item["status"] == "proposed" for item in candidates):
                return
        survivors = sorted(
            (item for item in candidates if item["status"] == "survived"),
            key=lambda item: (-item["screen"]["fixed"], -item["screen"]["graded_score"], item["number"]),
        )
        if not survivors:
            checkpoint["stagnation"] = checkpoint.get("stagnation", 0) + 1
            next_round_or_stop(db, job, budget, checkpoint)
            return
        first = db.get(AgentVersion, survivors[0]["version_id"])
        round_["queue"] = [item["version_id"] for item in survivors[1:]]
        checkpoint.update(round=round_, version_id=first.id)
        job.checkpoint = deepcopy(checkpoint)
        start_evaluation(db, job, first, suite)
        transition(db, job, "RETESTING")
    else:
        raise ValueError("Unknown workflow checkpoint state")
    db.flush()


def control(db, job, action):
    checkpoint = dict(job.checkpoint)
    if action == "pause":
        if job.state in INACTIVE:
            raise ValueError("Build is not running")
        checkpoint["resume_state"] = job.state
        transition(db, job, "PAUSED", checkpoint)
    elif action == "resume":
        if job.state not in ("PAUSED", "WAITING_FOR_APPROVAL"):
            raise ValueError("Build is not resumable")
        transition(db, job, checkpoint.get("resume_state", "BUILDING"), checkpoint)
    elif action == "cancel":
        if job.state in TERMINAL:
            raise ValueError("Build is already terminal")
        transition(db, job, "CANCELLED")
    else:
        raise ValueError("Unknown control action")


async def worker_tick(session_factory=SessionLocal):
    owner = uid()
    with session_factory() as db:
        candidate = db.scalar(
            select(BuildJob)
            .where(BuildJob.state.not_in(INACTIVE), (BuildJob.lease_until.is_(None) | (BuildJob.lease_until < now())))
            .order_by(BuildJob.created_at)
            .limit(1)
        )
        if not candidate:
            return False
        claimed = db.execute(
            update(BuildJob)
            .where(BuildJob.id == candidate.id, (BuildJob.lease_until.is_(None) | (BuildJob.lease_until < now())))
            .values(lease_owner=owner, lease_until=now() + timedelta(seconds=settings().worker_lease_seconds))
            .execution_options(synchronize_session=False)
        ).rowcount
        if not claimed:
            db.rollback()
            return True
        job_id = candidate.id
        db.commit()
    with session_factory() as db:
        job = db.scalar(select(BuildJob).where(BuildJob.id == job_id, BuildJob.lease_owner == owner).with_for_update())
        if not job:
            return True
        try:
            recover_reservations(db, job)
            db.commit()
            job = db.scalar(
                select(BuildJob)
                .where(BuildJob.id == job_id, BuildJob.lease_owner == owner)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if not job:
                return True
            await advance(db, job)
            if job.lease_owner != owner:
                db.rollback()
                return True
            job.lease_owner = None
            job.lease_until = None
            db.commit()
        except Exception as error:
            db.rollback()
            job = db.scalar(
                select(BuildJob)
                .where(BuildJob.id == job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if job.lease_owner != owner:
                return True
            job.error = type(error).__name__
            job.lease_owner = None
            job.lease_until = None
            transition(db, job, "FAILED")
            db.commit()
    return True
