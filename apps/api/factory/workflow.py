"""Checkpointed workflow: each worker tick persists one stage or one evaluation trial."""

from collections import Counter
from datetime import UTC, timedelta

from sqlalchemy import select, update

from factory.builder import design, design_tests, optimize, persist_version
from factory.config import settings
from factory.connectors import check_connection
from factory.db import SessionLocal, now, uid
from factory.evaluation import can_promote, development_evidence, evaluate_case, scorecard
from factory.models import (
    AgentRecord,
    AgentVersion,
    BuildIteration,
    BuildJob,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationSuite,
    UsageRecord,
)
from factory.runtime import BudgetExceeded, emit
from factory.schemas import AgentSpec, Budget

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
        job.checkpoint = checkpoint
    emit(db, job.org_id, "build_state", {"state": state, "iteration": job.iteration, "spent": job.spent}, job_id=job.id)


def start_evaluation(db, job, version, suite, validation=False):
    evaluation = EvaluationRun(org_id=job.org_id, version_id=version.id, suite_id=suite.id)
    db.add(evaluation)
    db.flush()
    job.checkpoint = {**job.checkpoint, "evaluation_id": evaluation.id, "validation": validation}


def record_role_usage(db, job, role, usage):
    job.spent += usage.get("cost", 0)
    db.add(
        UsageRecord(
            org_id=job.org_id, job_id=job.id, role=role, tokens=usage.get("tokens", 0), cost=usage.get("cost", 0)
        )
    )
    emit(db, job.org_id, "factory_role_usage", {"role": role, **usage}, job_id=job.id)


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
                    max_seconds=max(0, budget.max_seconds - elapsed),
                    usage=usage,
                )
                # User quality policy and resource ceilings remain authoritative.
                spec.quality_policy = AgentSpec.model_validate(version.spec).quality_policy
                version = persist_version(db, agent, spec, "Background requirements analysis and architecture")
                checkpoint["version_id"] = version.id
                job.checkpoint = checkpoint
                agent.name = spec.name
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
                        max_seconds=max(0, budget.max_seconds - elapsed),
                        usage=usage,
                    )
                    checkpoint["test_proposals"] = proposal.model_dump()
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
        completed = {
            (r.case_id, r.trial)
            for r in db.scalars(select(EvaluationResult).where(EvaluationResult.evaluation_run_id == evaluation.id))
        }
        remaining = [
            (case, trial) for case in cases for trial in range(case.trials) if (case.id, trial) not in completed
        ]
        if remaining:
            case, trial = remaining[0]
            result = await evaluate_case(
                db,
                evaluation,
                version,
                case,
                trial,
                max_cost=max(0, budget.max_cost - job.spent),
                max_seconds=max(0, budget.max_seconds - elapsed),
            )
            run = db.get(__import__("factory.models", fromlist=["ExecutionRun"]).ExecutionRun, result.execution_id)
            job.spent += run.metrics.get("cost", 0)
            if run.error == "BudgetExceeded":
                transition(
                    db,
                    job,
                    "BUDGET_EXHAUSTED",
                    {**checkpoint, "stop_reason": "insufficient_budget_before_provider_call"},
                )
                return
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
                },
                job_id=job.id,
            )
        else:
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
        if promoted:
            agent.best_version_id = version.id
            checkpoint.update(best_version_id=version.id, best_scorecard=card, stagnation=0)
        else:
            checkpoint["stagnation"] = checkpoint.get("stagnation", 0) + 1
        checkpoint.update(diagnosis=diagnosis, last_scorecard=card)
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
            job.checkpoint = checkpoint
            start_evaluation(db, job, db.get(AgentVersion, checkpoint["version_id"]), suite, validation=True)
            transition(db, job, "RETESTING")
        elif job.iteration >= budget.max_iterations or checkpoint["stagnation"] >= budget.stagnation_limit:
            transition(db, job, "BUDGET_EXHAUSTED", {**checkpoint, "stop_reason": "iterations_or_stagnation_limit"})
        else:
            transition(db, job, "OPTIMIZING", checkpoint)
    elif job.state == "OPTIMIZING":
        # Never pass regression/validation answer records into optimizer context.
        usage = {}
        try:
            candidate, hypothesis = await optimize(
                AgentSpec.model_validate(version.spec),
                checkpoint["diagnosis"]["development_failures"],
                max_cost=max(0, budget.max_cost - job.spent),
                max_seconds=max(0, budget.max_seconds - elapsed),
                usage=usage,
            )
        except Exception as error:
            record_role_usage(db, job, "optimizer", usage)
            job.error = type(error).__name__
            transition(db, job, "BUDGET_EXHAUSTED" if isinstance(error, BudgetExceeded) else "FAILED")
            return
        record_role_usage(db, job, "optimizer", usage)
        new_version = persist_version(db, agent, candidate, hypothesis)
        checkpoint["version_id"] = new_version.id
        job.checkpoint = checkpoint
        emit(
            db,
            job.org_id,
            "improvement_hypothesis",
            {"hypothesis": hypothesis, "version_id": new_version.id, "number": new_version.number},
            job_id=job.id,
        )
        start_evaluation(db, job, new_version, suite)
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
            await advance(db, job)
            job.lease_owner = None
            job.lease_until = None
            db.commit()
        except Exception as error:
            db.rollback()
            job = db.get(BuildJob, job_id)
            job.error = type(error).__name__
            job.lease_owner = None
            job.lease_until = None
            transition(db, job, "FAILED")
            db.commit()
    return True
