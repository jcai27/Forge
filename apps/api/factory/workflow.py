"""Checkpointed workflow: each worker tick persists one stage or one evaluation trial."""

import asyncio
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from agents.exceptions import MaxTurnsExceeded, ModelBehaviorError
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker

from factory.builder import ARCHITECT_OUTPUT_TOKENS, design, design_tests, mutable_view, optimize, persist_version
from factory.config import mode_for, settings
from factory.connectors import check_connection
from factory.db import SessionLocal, now, uid
from factory.evaluation import (
    ProviderUnavailable,
    can_promote,
    changed_selection_cases,
    confusions,
    contradicted_verifiers,
    development_evidence,
    evaluate_case,
    known_answers,
    passing_examples,
    scorecard,
    selection_score,
    uniformly_failing,
    verifiers_rejecting,
)
from factory.intake import context_payload, documents, truth_source
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
from factory.pricing import provider_unavailable
from factory.provider_accounting import BuildInterrupted, FactoryBudgetHooks, recover_reservations
from factory.release import playbook
from factory.research import OutboundScreen, tenant_markers
from factory.runtime import BudgetExceeded, emit
from factory.schemas import AgentSpec, Budget
from factory.security import known_secret_values

# BELOW_TARGET: the build ran to the end and its best version scored under the target on held-out
# cases. Nothing broke, which is what FAILED means.
TERMINAL = {"READY_FOR_REVIEW", "DEPLOYED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED", "BELOW_TARGET"}
WAITING = {"PAUSED", "WAITING_FOR_APPROVAL"}
INACTIVE = TERMINAL | WAITING
# Seconds to wait before trying again after the provider could not be reached. After the last one the
# build pauses with the reason, and resumes where it stopped.
RETRY_DELAYS = (5, 15, 45, 120, 300)


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
    if truth_source(db, agent) is None:
        raise ValueError("A build needs examples with correct answers, or a statement that the task needs none")
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
    # Always store a fresh object: an autoflush between two in-place edits of the same dict
    # would otherwise hide the second edit from change detection.
    checkpoint = deepcopy(job.checkpoint if checkpoint is None else checkpoint)
    # Time spent paused or waiting for a person is not the build's time.
    if state in WAITING:
        checkpoint.setdefault("idle_since", now().isoformat())
    elif "idle_since" in checkpoint:
        idle = (now() - utc(datetime.fromisoformat(checkpoint.pop("idle_since")))).total_seconds()
        checkpoint["idle_seconds"] = checkpoint.get("idle_seconds", 0) + max(0, idle)
    job.state = state
    job.checkpoint = checkpoint
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
REJECTED_PROPOSAL = (
    PermissionError,
    ValidationError,
    SchemaError,
    ModelBehaviorError,
    MaxTurnsExceeded,
    TimeoutError,
)


def drop_rejecting_verifiers(db, agent, spec):
    """Remove checks that a known-correct development answer would fail, before anything is run.

    Returns a note for the version's hypothesis. Running such a check costs a full pass in which
    every answer is marked wrong, and a repair attempt on top of each.
    """
    wrong = verifiers_rejecting(spec.verifiers, known_answers(db, agent.id, agent.org_id))
    if not wrong:
        return ""
    spec.verifiers = [verifier for verifier in spec.verifiers if verifier.id not in wrong]
    return f" [removed checks that reject known-correct answers: {', '.join(wrong)}]"


def round_strategy(candidates):
    """What to ask of the next proposal in a multi-candidate round.

    The first proposal is the model's own best judgment, with no steer. Measured with a capable model,
    prescribing a mechanism per proposal (instructions, examples, verifiers) pushed it away from the fix
    it would have chosen and into changes that regressed. Later proposals are asked only to differ from
    what the round already holds, so the round explores without being told how.
    """
    if not candidates:
        return None
    tried = "; ".join(item["hypothesis"][:200] for item in candidates[-4:])
    return (
        "Other proposals in this round already cover the following, so propose a genuinely different "
        f"change, and only if you believe it could be better: {tried}"
    )


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


def remaining_trials(db, evaluation, cases, extra=None):
    """(completed keys, [(case, trial)] still to run). `extra` asks for more trials of some cases than they declare."""
    completed = {
        (r.case_id, r.trial)
        for r in db.scalars(select(EvaluationResult).where(EvaluationResult.evaluation_run_id == evaluation.id))
    }
    remaining = [
        (case, trial)
        for case in cases
        for trial in range((extra or {}).get(case.id, case.trials))
        if (case.id, trial) not in completed
    ]
    return completed, remaining


def trial_event(db, job, evaluation, case, trial, result, done, total):
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
            "completed": done,
            "total": total,
            "failures": result.failures,
            "screen": evaluation.status == "screening",
        },
        job_id=job.id,
    )


async def run_next_trial(db, job, budget, elapsed, checkpoint, evaluation, version, cases, extra=None):
    """Run one remaining (case, trial). Returns "ran", "done", "interrupted", "stopped" or "unavailable"."""
    completed, remaining = remaining_trials(db, evaluation, cases, extra)
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
    except ProviderUnavailable:
        return "unavailable"
    run = db.get(ExecutionRun, result.execution_id)
    job.spent += max(0, run.metrics.get("cost", 0) - run.metrics.get("build_accounted_cost", 0))
    run.metrics = {**run.metrics, "build_accounted_cost": run.metrics.get("cost", 0)}
    if run.error == "BudgetExceeded":
        transition(
            db, job, "BUDGET_EXHAUSTED", {**checkpoint, "stop_reason": "insufficient_budget_before_provider_call"}
        )
        return "stopped"
    trial_event(db, job, evaluation, case, trial, result, len(completed) + 1, len(completed) + len(remaining))
    return "ran"


def trial_width(db, version):
    """How many trials of this version may run side by side.

    Only live trials gain from it; demo trials are instant. Each parallel trial works in its own
    database session. SQLite has one writer, and a trial that calls tools holds a write open across
    the call, so on SQLite only an agent without tools is run in parallel.
    """
    width = settings().evaluation_concurrency
    if width <= 1 or mode_for(version.spec.get("template")) != "live":
        return 1
    tools = version.spec.get("tools") or version.spec.get("generated_tools")
    if db.get_bind().dialect.name == "sqlite" and tools:
        return 1
    return width


async def run_trials(db, job, budget, elapsed, checkpoint, evaluation, version, cases, extra=None):
    """Run the next trials of a pass, several at once where that is safe.

    Returns "ran", "done", "interrupted", "stopped", "unavailable" (nothing ran: the provider could not
    be reached) or "throttled" (some ran, some could not).
    """
    width = trial_width(db, version)
    if width == 1:
        return await run_next_trial(db, job, budget, elapsed, checkpoint, evaluation, version, cases, extra)
    completed, remaining = remaining_trials(db, evaluation, cases, extra)
    if not remaining:
        return "done"
    total, batch = len(completed) + len(remaining), remaining[:width]
    owner, state = job.lease_owner, job.state
    job_id, evaluation_id, version_id = job.id, evaluation.id, version.id
    limits = max(0, budget.max_cost - job.spent), max(0, budget.max_seconds - elapsed)
    # Release the build row: each trial reserves, settles and commits through its own session.
    db.commit()
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)

    async def one(case_id, trial):
        with sessions() as own:
            own_job = own.get(BuildJob, job_id)
            own_evaluation, own_version = own.get(EvaluationRun, evaluation_id), own.get(AgentVersion, version_id)
            case = own.get(EvaluationCase, case_id)
            try:
                result = await evaluate_case(
                    own,
                    own_evaluation,
                    own_version,
                    case,
                    trial,
                    max_cost=limits[0],
                    max_seconds=limits[1],
                    job=own_job,
                )
            except BuildInterrupted:
                own.rollback()
                return "interrupted"
            except ProviderUnavailable:
                own.commit()
                return "unavailable"
            # No await from here to the commit: the build row is locked for exactly this bookkeeping.
            run = own.get(ExecutionRun, result.execution_id)
            own.scalar(
                select(BuildJob)
                .where(BuildJob.id == job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            own_job.spent += max(0, run.metrics.get("cost", 0) - run.metrics.get("build_accounted_cost", 0))
            run.metrics = {**run.metrics, "build_accounted_cost": run.metrics.get("cost", 0)}
            if run.error == "BudgetExceeded":
                own.commit()
                return "stopped"
            done = own.scalar(
                select(func.count())
                .select_from(EvaluationResult)
                .where(EvaluationResult.evaluation_run_id == evaluation_id)
            )
            trial_event(own, own_job, own_evaluation, case, trial, result, done, total)
            own.commit()
            return "ran"

    outcomes = await asyncio.gather(*(one(case.id, trial) for case, trial in batch), return_exceptions=True)
    # Take the build row back and see what the trials, or anyone else, did to it meanwhile.
    db.scalar(select(BuildJob).where(BuildJob.id == job_id).with_for_update().execution_options(populate_existing=True))
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            raise outcome
    if job.lease_owner != owner or job.state != state or "interrupted" in outcomes:
        return "interrupted"
    if "stopped" in outcomes:
        transition(
            db, job, "BUDGET_EXHAUSTED", {**checkpoint, "stop_reason": "insufficient_budget_before_provider_call"}
        )
        return "stopped"
    if "unavailable" in outcomes:
        return "throttled" if "ran" in outcomes else "unavailable"
    return "ran"


async def run_pass(db, job, budget, elapsed, checkpoint, evaluation, version, cases, extra=None):
    """One step of a pass, with waiting and resuming handled. Returns "ran", "done" or "halt"."""
    outcome = await run_trials(db, job, budget, elapsed, checkpoint, evaluation, version, cases, extra)
    if outcome in ("interrupted", "stopped"):
        return "halt"
    if outcome == "unavailable":
        provider_down(db, job, checkpoint)
        return "halt"
    if outcome == "throttled":
        # Some trials got through. Keep them, and give the provider a moment before the rest.
        checkpoint["not_before"] = (now() + timedelta(seconds=RETRY_DELAYS[0])).isoformat()
        job.checkpoint = deepcopy(checkpoint)
        return "halt"
    provider_back(job, checkpoint)
    return outcome


def provider_down(db, job, checkpoint, error=None):
    """The model provider could not be reached. Wait and try the same step again; after a while, pause.

    Nothing is scored and nothing is abandoned: the build keeps its place. The call that failed keeps
    its reservation as an unknown charge, and the retry is a new call with its own.
    """
    failures = checkpoint.get("provider_failures", 0) + 1
    emit(
        db,
        job.org_id,
        "provider_unavailable",
        {"attempt": failures, "error_type": type(error).__name__ if error else None},
        job_id=job.id,
    )
    if failures > len(RETRY_DELAYS):
        checkpoint.pop("provider_failures", None)
        checkpoint.pop("not_before", None)
        transition(
            db,
            job,
            "PAUSED",
            {
                **checkpoint,
                "resume_state": job.state,
                "waiting_reason": "The model provider could not be reached. Nothing was lost: resume the build when the connection is back.",
            },
        )
        return
    checkpoint["provider_failures"] = failures
    checkpoint["not_before"] = (now() + timedelta(seconds=RETRY_DELAYS[failures - 1])).isoformat()
    job.checkpoint = deepcopy(checkpoint)


def provider_back(job, checkpoint):
    if "provider_failures" in checkpoint or "not_before" in checkpoint:
        checkpoint.pop("provider_failures", None)
        checkpoint.pop("not_before", None)
        job.checkpoint = deepcopy(checkpoint)


def pass_needs(db, suite, checkpoint, splits):
    """(cost, seconds) a pass over these splits is expected to need, from what trials have cost so far.

    Besides what the trials will cost, a budget must have room for the amount each call sets aside
    before it starts, for as many calls as run at once.
    """
    card = checkpoint.get("best_scorecard")
    if not card or not card.get("total") or suite is None:
        return 0.0, 0.0
    trials = sum(
        case.trials
        for case in db.scalars(
            select(EvaluationCase).where(EvaluationCase.suite_id == suite.id, EvaluationCase.split.in_(splits))
        )
    )
    if not trials:
        return 0.0, 0.0
    width = max(1, settings().evaluation_concurrency)
    cost = trials * card["cost"] / card["total"] + width * card.get("peak_reservation", 0)
    return cost, trials * card["mean_latency_ms"] / 1000 / width


def stop_at_limit(db, job, checkpoint, suite, reason="iterations_or_stagnation_limit"):
    """The build has run out of rounds, money or time. Before it ends, measure its best version on the
    held-out cases.

    Most builds end here rather than at the target, and without this number nobody could say how good
    the result is. The build still ends as exhausted: the held-out score is reported, not rewarded.
    """
    checkpoint.pop("round", None)
    best = db.get(AgentVersion, checkpoint.get("best_version_id") or "")
    held_out = suite is not None and db.scalar(
        select(EvaluationCase.id)
        .where(EvaluationCase.suite_id == suite.id, EvaluationCase.split == "validation")
        .limit(1)
    )
    if best is None or not held_out:
        transition(db, job, "BUDGET_EXHAUSTED", {**checkpoint, "stop_reason": reason})
        return
    checkpoint.update(version_id=best.id, limit_stop=reason)
    job.checkpoint = deepcopy(checkpoint)
    start_evaluation(db, job, best, suite, validation=True)
    transition(db, job, "RETESTING")


def next_round_or_stop(db, job, budget, checkpoint, suite):
    """After a round with no promotion: stop at the limits, otherwise propose again from the parent."""
    checkpoint.pop("round", None)
    if job.iteration >= budget.max_iterations or checkpoint.get("stagnation", 0) >= budget.stagnation_limit:
        stop_at_limit(db, job, checkpoint, suite)
    else:
        transition(db, job, "OPTIMIZING", checkpoint)


async def advance(db, job):
    if job.state in INACTIVE:
        return
    budget = Budget.model_validate(job.budget)
    checkpoint = dict(job.checkpoint)
    if checkpoint.get("not_before"):
        wait = (utc(datetime.fromisoformat(checkpoint["not_before"])) - now()).total_seconds()
        if wait > 0:
            await asyncio.sleep(min(wait, 2))
            return
    elapsed = (now() - utc(job.created_at)).total_seconds() - checkpoint.get("idle_seconds", 0)
    if job.spent > budget.max_cost or elapsed > budget.max_seconds:
        transition(db, job, "BUDGET_EXHAUSTED", {**checkpoint, "stop_reason": "cost_or_elapsed_budget"})
        return
    agent = db.get(AgentRecord, job.agent_id)
    version = db.get(AgentVersion, checkpoint["version_id"])
    suite = db.scalar(select(EvaluationSuite).where(EvaluationSuite.agent_id == agent.id))
    if job.state == "OPTIMIZING" and not checkpoint.get("round") and checkpoint.get("best_version_id"):
        # About to start another round. If there is not room for it and for the final held-out
        # measurement after it, stop improving now and spend what is left on that measurement, so a
        # build that runs short of money or time still ends with an honest score for its best version.
        round_cost, round_seconds = pass_needs(db, suite, checkpoint, ("development", "selection", "regression"))
        final_cost, final_seconds = pass_needs(db, suite, checkpoint, ("validation",))
        short = (
            job.spent + round_cost + final_cost > budget.max_cost
            or elapsed + round_seconds + final_seconds > budget.max_seconds
        )
        if final_cost and short:
            stop_at_limit(db, job, checkpoint, suite, reason="cost_or_elapsed_budget")
            return
    if job.state == "DRAFT":
        transition(db, job, "DISCOVERING")
    elif job.state == "DISCOVERING":
        spec = AgentSpec.model_validate(version.spec)
        for connection_id in spec.connection_ids:
            check_connection(db, job.org_id, connection_id)
        if not spec.tools and (spec.connection_ids or spec.template != "custom"):
            # Only a custom agent may work from its input alone; a connection that offers nothing is a fault.
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
        if mode_for(agent.template) == "live":
            usage = {}
            try:
                spec = await design(
                    db,
                    agent,
                    version.spec["connection_ids"],
                    max_cost=max(0, budget.max_cost - job.spent),
                    max_seconds=min(300, max(0, budget.max_seconds - elapsed)),
                    usage=usage,
                    hooks=FactoryBudgetHooks(
                        max(0, budget.max_cost - job.spent),
                        db,
                        job,
                        "requirements_architect",
                        max_seconds=min(300, max(0, budget.max_seconds - elapsed)),
                        max_output_tokens=ARCHITECT_OUTPUT_TOKENS,
                    ),
                )
                # User quality policy and resource ceilings remain authoritative.
                spec.quality_policy = AgentSpec.model_validate(version.spec).quality_policy
                note = drop_rejecting_verifiers(db, agent, spec)
                version = persist_version(db, agent, spec, "Background requirements analysis and architecture" + note)
                checkpoint["version_id"] = version.id
                job.checkpoint = deepcopy(checkpoint)
                agent.name = spec.name
            except BuildInterrupted:
                return
            except Exception as error:
                record_role_usage(db, job, "requirements_architect", usage)
                if provider_unavailable(error):
                    provider_down(db, job, checkpoint, error)
                    return
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
            if mode_for(agent.template) == "live" and not checkpoint.get("test_proposals"):
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
                    if provider_unavailable(error):
                        provider_down(db, job, checkpoint, error)
                        return
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
        splits = ["validation"] if checkpoint.get("validation") else ["development", "selection", "regression"]
        cases = list(
            db.scalars(
                select(EvaluationCase)
                .where(EvaluationCase.suite_id == suite.id, EvaluationCase.split.in_(splits))
                .order_by(EvaluationCase.id)
            )
        )
        confirming = checkpoint.get("confirm_cases")
        if confirming:
            cases = [case for case in cases if case.id in confirming]
        outcome = await run_pass(db, job, budget, elapsed, checkpoint, evaluation, version, cases, confirming)
        if outcome == "halt":
            return
        if confirming and outcome == "done":
            checkpoint.pop("confirm_cases")
            evaluation.scorecard = scorecard(db, evaluation)
            transition(db, job, "ANALYZING", checkpoint)
            return
        if (
            outcome == "ran"
            and not confirming
            and not checkpoint.get("validation")
            and uniformly_failing(db, evaluation)
        ):
            # Every trial so far failed the same way: the version is broken. Stop paying for the proof.
            emit(db, job.org_id, "evaluation_stopped_early", {"evaluation_id": evaluation.id}, job_id=job.id)
            outcome = "done"
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
            if checkpoint.get("limit_stop"):
                transition(
                    db,
                    job,
                    "BUDGET_EXHAUSTED",
                    {**checkpoint, "validation_scorecard": card, "stop_reason": checkpoint["limit_stop"]},
                )
                return
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
                    "BELOW_TARGET",
                    {
                        **checkpoint,
                        "validation_scorecard": card,
                        "stop_reason": "held_out_score_below_target",
                    },
                )
            return
        wrong = contradicted_verifiers(db, evaluation)
        if wrong and checkpoint.get("verifiers_corrected") != version.id:
            # A check that rejects known-correct answers makes every score of this version meaningless.
            # Take it out and measure again before anything is compared, promoted or shown to the optimizer.
            spec = AgentSpec.model_validate(version.spec)
            spec.verifiers = [verifier for verifier in spec.verifiers if verifier.id not in wrong]
            corrected = persist_version(
                db, agent, spec, f"Removed checks that rejected correct answers: {', '.join(wrong)}"[:1000]
            )
            emit(
                db,
                job.org_id,
                "verifiers_contradicted",
                {"version_id": version.id, "corrected_version_id": corrected.id, "verifiers": wrong},
                job_id=job.id,
            )
            checkpoint.update(version_id=corrected.id, verifiers_corrected=corrected.id)
            job.checkpoint = deepcopy(checkpoint)
            start_evaluation(db, job, corrected, suite)
            transition(db, job, "RETESTING")
            return
        evidence = development_evidence(db, evaluation)
        baseline = checkpoint.get("best_scorecard")
        policy = AgentSpec.model_validate(version.spec).quality_policy
        if (
            baseline
            and checkpoint.get("confirmed") != evaluation.id
            and can_promote(card, baseline, policy.model_dump())
        ):
            # About to be kept on the strength of a few unseen cases that changed. An agent's answers
            # vary from run to run, so run exactly those cases once more before believing it.
            changed = changed_selection_cases(card, baseline)
            if changed:
                checkpoint.update(confirmed=evaluation.id, confirm_cases={cid: done + 1 for cid, done in changed})
                emit(db, job.org_id, "promotion_confirming", {"cases": len(changed)}, job_id=job.id)
                transition(db, job, "RETESTING", checkpoint)
                return
        promoted = can_promote(card, baseline, policy.model_dump())
        diagnosis = {
            "development_failures": evidence,
            "confusions": confusions(evidence),
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
            # An aggregate only: the builder learns whether a change generalised, never which cases moved.
            "unseen_score": selection_score(card) if card.get("selection_cases") else None,
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
            selection_score(checkpoint.get("best_scorecard") or {"score": 0})
            >= max(budget.target_score, policy.minimum_score)
            and checkpoint.get("best_scorecard", {}).get("distinct_cases", 0) >= policy.minimum_cases
        ):
            checkpoint["version_id"] = checkpoint["best_version_id"]
            checkpoint.pop("round", None)
            job.checkpoint = deepcopy(checkpoint)
            start_evaluation(db, job, db.get(AgentVersion, checkpoint["version_id"]), suite, validation=True)
            transition(db, job, "RETESTING")
        elif job.iteration >= budget.max_iterations or checkpoint["stagnation"] >= budget.stagnation_limit:
            stop_at_limit(db, job, checkpoint, suite)
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
        spec = AgentSpec.model_validate(version.spec)
        live = mode_for(agent.template) == "live"
        researching = live and bool(budget.investigator_turns) and settings().research_enabled
        # Time for one proposal. A reasoning model thinking through sixty cases needs minutes, not one.
        ceiling = 180 if budget.investigator_turns == 0 else 480 if researching else 300
        seconds = min(ceiling, max(0, budget.max_seconds - elapsed))
        investigation = None
        if live and budget.investigator_turns:
            research = None
            if researching:
                evidence = [
                    *checkpoint["diagnosis"]["development_failures"],
                    *checkpoint.get("best_passing", []),
                    # The customer's documents are in the builder's context, so they must not leave either.
                    *({"input": row.text} for row in documents(db, agent)),
                ]
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
                context=context_payload(db, agent, budget=20_000) if live else None,
                summary=checkpoint["diagnosis"].get("confusions"),
                live=live,
                max_cost=max(0, budget.max_cost - job.spent),
                max_seconds=seconds,
                usage=usage,
                secret_values=known_secret_values(db, job.org_id),
                tools=investigation.tools() if investigation else None,
                max_turns=budget.investigator_turns + 2,
                strategy=round_strategy(candidates) if budget.candidates_per_round > 1 else None,
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
            if provider_unavailable(error):
                provider_down(db, job, checkpoint, error)
                return
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
            hypothesis = (hypothesis + drop_rejecting_verifiers(db, agent, candidate))[:1000]
            seen = {mutable_view(db.get(AgentVersion, item["version_id"]).spec) for item in candidates}
            if mutable_view(candidate) == mutable_view(spec):
                # Identical to its already-evaluated parent: a full evaluation could only repeat its score.
                rejection = "UnchangedProposal"
            elif mutable_view(candidate) in seen:
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
        # The deterministic ladder has no more ideas once it repeats itself.
        exhausted = rejection in ("DuplicateProposal", "UnchangedProposal") and not live
        if len(candidates) + round_["discarded"] < budget.candidates_per_round and not exhausted:
            job.checkpoint = deepcopy(checkpoint)
            return
        if not candidates:
            checkpoint["stagnation"] = checkpoint.get("stagnation", 0) + 1
            next_round_or_stop(db, job, budget, checkpoint, suite)
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
            outcome = await run_pass(db, job, budget, elapsed, checkpoint, screen, candidate_version, cases)
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
            next_round_or_stop(db, job, budget, checkpoint, suite)
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
        # The reason for waiting and where to go back to belong to this wait only.
        target = checkpoint.pop("resume_state", "BUILDING")
        checkpoint.pop("waiting_reason", None)
        transition(db, job, target, checkpoint)
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
