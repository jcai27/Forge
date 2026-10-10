import asyncio
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from agents import Agent, Model, ModelResponse, Usage
from openai import AsyncOpenAI
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from factory.config import settings
from factory.db import uid
from factory.models import BuildJob, EvaluationCase, ExecutionRun, UsageRecord
from factory.provider_accounting import BuildInterrupted, recover_reservations
from factory.qualitative import grade_rubric
from factory.schemas import Budget
from factory.workflow import control, new_job


def grading_fixture(db, seeded):
    org, _, agent, version, suite, _ = seeded
    case = EvaluationCase(
        org_id=org.id,
        suite_id=suite.id,
        name="Explicit local rubric contract",
        split="development",
        input={},
        assertions=[],
        rubric={"criteria": ["Is clear"], "threshold": 0.8},
    )
    run = ExecutionRun(
        org_id=org.id,
        version_id=version.id,
        mode="demo",
        status="completed",
        input={},
        output={"text": "Clear fixture"},
        metrics={"cost": 0, "tokens": 0},
    )
    job = new_job(db, agent, Budget())
    job.state = "TESTING"
    db.add_all([case, run])
    db.commit()
    return version, case, run, job


class GradingProvider(Model):
    def __init__(self, callback=None, tokens=30):
        self.callback, self.tokens, self.calls = callback, tokens, 0

    async def get_response(self, *args, **kwargs):
        self.calls += 1
        if self.callback:
            observed = self.callback()
            if inspect.isawaitable(observed):
                await observed
        return ModelResponse(
            output=[
                ResponseOutputMessage(
                    type="message",
                    role="assistant",
                    id=uid(),
                    status="completed",
                    content=[
                        ResponseOutputText(
                            type="output_text",
                            text=json.dumps(
                                {
                                    "criteria": [
                                        {
                                            "criterion": "Is clear",
                                            "score": 0.9,
                                            "evidence": "Explicit local provider fixture",
                                        }
                                    ]
                                }
                            ),
                            annotations=[],
                        )
                    ],
                )
            ],
            usage=Usage(requests=1, input_tokens=self.tokens - 10, output_tokens=10, total_tokens=self.tokens),
            response_id=uid(),
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


def install_provider(monkeypatch, provider):
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "explicit-local-grading-contract")
    monkeypatch.setattr("factory.qualitative.Agent", lambda **kwargs: Agent(**{**kwargs, "model": provider}))


@pytest.mark.asyncio
@pytest.mark.parametrize("build_funded", [False, True])
async def test_rubric_commits_reservation_before_sdk_dispatch_and_settles_observed_usage(
    db, seeded, monkeypatch, build_funded
):
    version, case, run, job = grading_fixture(db, seeded)
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)

    def during_dispatch():
        with sessions() as other:
            usage = other.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
            assert usage.status == "pending" and usage.reserved_cost > 0
            assert usage.cost == usage.tokens == 0
            observed_run = other.get(ExecutionRun, run.id)
            assert observed_run.metrics["reserved_cost"] == usage.reserved_cost
            assert observed_run.metrics["cost"] == 0
            if build_funded:
                assert usage.job_id == job.id and other.get(BuildJob, job.id).spent == usage.reserved_cost
            else:
                assert usage.job_id is None

    provider = GradingProvider(during_dispatch)
    install_provider(monkeypatch, provider)
    checks = await grade_rubric(db, version, run, case, job=job if build_funded else None)
    usage = db.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
    assert checks[0]["passed"] and checks[0]["actual"] == 0.9
    assert provider.calls == 1 and usage.role == "rubric_evaluator"
    assert usage.status == "recorded" and usage.tokens == run.metrics["grading_tokens"] == 30
    assert usage.reserved_cost == run.metrics["reserved_cost"] == 0
    assert usage.cost == run.metrics["cost"] == run.metrics["grading_cost"] == 30 * settings().estimated_token_cost
    if build_funded:
        assert job.spent == pytest.approx(usage.cost)
        assert run.metrics["build_accounted_cost"] == usage.cost


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["pause", "cancel", "lease_transfer", "redirect", "provider_error"])
async def test_rubric_retains_unknown_charges_and_preserves_worker_control(db, seeded, monkeypatch, action):
    version, case, run, job = grading_fixture(db, seeded)
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)

    def during_dispatch():
        with sessions() as other:
            assert other.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id)).status == "pending"
            observed = other.get(BuildJob, job.id)
            if action == "lease_transfer":
                observed.lease_owner = "another-worker"
            elif action == "redirect":
                from factory.api import redirect_build
                from factory.schemas import AgentSpec, RedirectBuild
                from factory.security import Principal

                org, user, *_ = seeded
                spec = AgentSpec.model_validate(version.spec)
                spec.purpose = "Revised restaurant orders with explicit alias resolution"
                redirect_build(
                    job.id,
                    RedirectBuild(
                        expected_version_id=version.id, reason="Explicit local redirection contract", spec=spec
                    ),
                    Principal(user.id, org.id, "admin"),
                    other,
                )
            elif action != "provider_error":
                control(other, observed, action)
            other.commit()
        if action == "provider_error":
            raise RuntimeError("Explicit simulated grading transport failure")

    install_provider(monkeypatch, GradingProvider(during_dispatch))
    if action == "provider_error":
        checks = await grade_rubric(db, version, run, case, job=job)
        assert checks[0]["pending"] and "actual" not in checks[0]
    else:
        with pytest.raises(BuildInterrupted):
            await grade_rubric(db, version, run, case, job=job)
    db.expire_all()
    usage = db.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
    if action == "provider_error":
        assert usage.status == "uncertain" and usage.cost == usage.tokens == 0
        assert job.spent == run.metrics["reserved_cost"] == usage.reserved_cost > 0
    else:
        assert usage.status == "recorded" and job.spent == pytest.approx(usage.cost)
        assert (
            job.state
            == {"pause": "PAUSED", "cancel": "CANCELLED", "lease_transfer": "TESTING", "redirect": "BUILDING"}[action]
        )
        if action == "lease_transfer":
            assert job.lease_owner == "another-worker"
        elif action == "redirect":
            assert job.checkpoint["version_id"] != version.id


@pytest.mark.asyncio
async def test_rubric_http_failure_is_not_retried_under_one_reservation(db, seeded, monkeypatch):
    version, case, run, job = grading_fixture(db, seeded)
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(500, json={"error": {"message": "Local grading failure", "type": "server_error"}})

    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "explicit-local-grading-http-contract")
    monkeypatch.setattr(
        "factory.builder.AsyncOpenAI",
        lambda **kwargs: AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))),
    )
    checks = await grade_rubric(db, version, run, case, job=job)
    usage = db.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
    assert len(requests) == 1 and requests[0].url.path == "/v1/responses"
    assert checks[0]["pending"] and "actual" not in checks[0]
    assert usage.status == "uncertain" and job.spent == usage.reserved_cost > 0
    assert usage.tokens == usage.cost == 0


@pytest.mark.asyncio
async def test_rubric_observed_over_budget_usage_is_not_lost_or_returned_as_a_score(db, seeded, monkeypatch):
    version, case, run, job = grading_fixture(db, seeded)
    install_provider(monkeypatch, GradingProvider(tokens=1_000_000))
    checks = await grade_rubric(db, version, run, case, job=job)
    usage = db.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
    assert checks[0]["pending"] and checks[0]["evidence"].endswith("BudgetExceeded")
    assert "actual" not in checks[0]
    assert usage.status == "recorded" and usage.tokens == 1_000_000 and usage.reserved_cost == 0
    assert job.spent == run.metrics["cost"] == usage.cost


@pytest.mark.asyncio
async def test_rubric_process_kill_preserves_charge_and_recovery_budget(db, seeded, tmp_path, monkeypatch):
    version, case, run, job = grading_fixture(db, seeded)
    marker = tmp_path / "rubric-dispatch"
    environment = {
        **os.environ,
        "DATABASE_URL": db.get_bind().url.render_as_string(hide_password=False),
        "EXECUTION_MODE": "live",
        "OPENAI_API_KEY": "explicit-local-rubric-no-network",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    schema = db.get_bind().get_execution_options().get("schema_translate_map", {}).get(None)
    if schema:
        environment["TEST_SCHEMA"] = schema
    helper = Path(__file__).parent / "helpers" / "crash_rubric.py"
    process = subprocess.Popen(
        [sys.executable, str(helper), run.id, case.id, job.id, str(marker)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                _, stderr = process.communicate()
                raise AssertionError(stderr)
            await asyncio.sleep(0.02)
        assert marker.exists()
        process.kill()
        process.communicate(timeout=5)
        db.expire_all()
        usage = db.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
        reservation = usage.reserved_cost
        assert usage.status == "pending" and usage.tokens == usage.cost == 0
        assert job.spent == run.metrics["reserved_cost"] == reservation > 0
        recover_reservations(db, job)
        job.budget = {**job.budget, "max_cost": reservation * 1.5}
        db.commit()
        assert usage.status == "uncertain" and job.spent == reservation
        provider = GradingProvider()
        install_provider(monkeypatch, provider)
        checks = await grade_rubric(db, version, run, case, max_cost=reservation * 1.5, job=job)
        assert checks[0]["pending"] and checks[0]["evidence"].endswith("BudgetExceeded")
        assert provider.calls == 0 and job.spent == reservation
        assert len(list(db.scalars(select(UsageRecord).where(UsageRecord.run_id == run.id)))) == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("pause_during_grade", [False, True])
async def test_worker_rubric_accounting_is_once_only_and_preserves_pause(db, seeded, monkeypatch, pause_during_grade):
    from factory import evaluation, runtime
    from factory.models import EvaluationResult
    from factory.workflow import start_evaluation, worker_tick

    # This test follows one trial through one worker tick.
    monkeypatch.setattr(settings(), "evaluation_concurrency", 1)
    _, _, agent, version, suite, _ = seeded
    job = new_job(db, agent, Budget())
    start_evaluation(db, job, version, suite)
    job.state = "TESTING"
    first = db.scalar(
        select(EvaluationCase)
        .where(EvaluationCase.suite_id == suite.id, EvaluationCase.split.in_(["development", "regression"]))
        .order_by(EvaluationCase.id)
    )
    first.rubric = {"criteria": ["Is clear"], "threshold": 0.8}
    db.commit()
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    original = runtime.execute

    async def fixture_execution(*args, **kwargs):
        return await original(*args, **kwargs, mode="demo")

    monkeypatch.setattr(evaluation, "execute", fixture_execution)

    def during_dispatch():
        if pause_during_grade:
            with sessions() as other:
                control(other, other.get(BuildJob, job.id), "pause")
                other.commit()

    install_provider(monkeypatch, GradingProvider(during_dispatch))
    assert await worker_tick(sessions)
    db.expire_all()
    usage = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
    assert usage.role == "rubric_evaluator" and usage.status == "recorded" and usage.tokens == 30
    assert job.spent == pytest.approx(usage.cost) and job.lease_owner is None
    results = list(
        db.scalars(
            select(EvaluationResult).where(EvaluationResult.evaluation_run_id == job.checkpoint["evaluation_id"])
        )
    )
    if pause_during_grade:
        assert job.state == "PAUSED" and results == []
    else:
        assert job.state == "TESTING" and len(results) == 1
        run = db.get(ExecutionRun, results[0].execution_id)
        assert run.mode == "demo" and run.metrics["build_accounted_cost"] == usage.cost
        assert next(check for check in results[0].checks if check["category"] == "qualitative")["actual"] == 0.9


@pytest.mark.asyncio
async def test_manual_retry_preserves_deterministic_failure_and_avoids_charging_historical_usage_twice(
    db, seeded, monkeypatch
):
    from factory.api import retry_rubric_grade
    from factory.models import EvaluationResult, EvaluationRun
    from factory.security import Principal

    version, case, run, job = grading_fixture(db, seeded)
    historical_cost = 10 * settings().estimated_token_cost
    run.metrics = {"tokens": 10, "cost": historical_cost}
    job.spent = historical_cost
    evaluation = EvaluationRun(org_id=run.org_id, version_id=version.id, suite_id=case.suite_id)
    db.add(evaluation)
    db.flush()
    job.checkpoint = {**job.checkpoint, "evaluation_id": evaluation.id}
    result = EvaluationResult(
        org_id=run.org_id,
        evaluation_run_id=evaluation.id,
        case_id=case.id,
        execution_id=run.id,
        passed=False,
        checks=[
            {"category": "structured_accuracy", "passed": False},
            {"category": "qualitative", "passed": False, "pending": True},
        ],
        failures=["structured_accuracy", "qualitative"],
    )
    db.add_all([result, UsageRecord(org_id=run.org_id, run_id=run.id, tokens=10, cost=historical_cost)])
    db.commit()
    org, user, *_ = seeded
    install_provider(monkeypatch, GradingProvider())
    await retry_rubric_grade(result.id, Principal(user.id, org.id, "admin"), db)
    observed = 30 * settings().estimated_token_cost
    assert job.spent == pytest.approx(historical_cost + observed)
    assert run.metrics["build_accounted_cost"] == run.metrics["cost"] == pytest.approx(job.spent)
    assert result.passed is False and result.failures == ["structured_accuracy"]
    assert not any(check.get("pending") for check in result.checks)


@pytest.mark.asyncio
async def test_interleaved_manual_retries_keep_both_charges_but_publish_one_grade(db, seeded, monkeypatch):
    from fastapi import HTTPException

    from factory.api import retry_rubric_grade
    from factory.models import EvaluationResult, EvaluationRun
    from factory.security import Principal

    version, case, run, job = grading_fixture(db, seeded)
    evaluation = EvaluationRun(org_id=run.org_id, version_id=version.id, suite_id=case.suite_id)
    db.add(evaluation)
    db.flush()
    job.checkpoint = {**job.checkpoint, "evaluation_id": evaluation.id}
    result = EvaluationResult(
        org_id=run.org_id,
        evaluation_run_id=evaluation.id,
        case_id=case.id,
        execution_id=run.id,
        passed=False,
        checks=[{"category": "qualitative", "passed": False, "pending": True}],
        failures=["qualitative"],
    )
    db.add(result)
    db.commit()
    org, user, *_ = seeded
    actor = Principal(user.id, org.id, "admin")
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)

    async def during_dispatch():
        if provider.calls == 1:
            with sessions() as other:
                await retry_rubric_grade(result.id, actor, other)

    provider = GradingProvider(during_dispatch)
    install_provider(monkeypatch, provider)
    with pytest.raises(HTTPException) as error:
        await retry_rubric_grade(result.id, actor, db)
    assert error.value.status_code == 409 and "already resolved" in error.value.detail
    db.rollback()
    db.expire_all()
    assert provider.calls == 2 and result.passed
    records = list(db.scalars(select(UsageRecord).where(UsageRecord.run_id == run.id)))
    assert len(records) == 2 and all(record.status == "recorded" and record.tokens == 30 for record in records)
    assert job.spent == pytest.approx(sum(record.cost for record in records))
    assert run.metrics["cost"] == pytest.approx(job.spent) and run.metrics["reserved_cost"] == 0
    assert result.checks[0]["actual"] == 0.9 and "pending" not in result.checks[0]


@pytest.mark.asyncio
async def test_manual_retry_can_use_remaining_budget_without_refunding_unknown_charge(db, seeded, monkeypatch):
    from factory.api import retry_rubric_grade
    from factory.models import EvaluationResult, EvaluationRun
    from factory.security import Principal

    version, case, run, job = grading_fixture(db, seeded)

    def transport_failure():
        raise RuntimeError("Explicit unknown local provider charge")

    install_provider(monkeypatch, GradingProvider(transport_failure))
    checks = await grade_rubric(db, version, run, case, job=job)
    assert checks[0]["pending"]
    original = db.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
    reservation = original.reserved_cost
    evaluation = EvaluationRun(org_id=run.org_id, version_id=version.id, suite_id=case.suite_id)
    db.add(evaluation)
    db.flush()
    job.checkpoint = {**job.checkpoint, "evaluation_id": evaluation.id}
    job.budget = {**job.budget, "max_cost": reservation * 2.1}
    result = EvaluationResult(
        org_id=run.org_id,
        evaluation_run_id=evaluation.id,
        case_id=case.id,
        execution_id=run.id,
        passed=False,
        checks=checks,
        failures=["qualitative"],
    )
    db.add(result)
    db.commit()
    org, user, *_ = seeded
    provider = GradingProvider()
    install_provider(monkeypatch, provider)
    await retry_rubric_grade(result.id, Principal(user.id, org.id, "admin"), db)
    assert provider.calls == 1 and result.passed
    assert original.status == "uncertain" and original.reserved_cost == reservation
    observed = 30 * settings().estimated_token_cost
    assert job.spent == pytest.approx(reservation + observed)
    assert run.metrics["reserved_cost"] == evaluation.scorecard["reserved_cost"] == reservation
    assert evaluation.scorecard["cost"] == observed


def test_promotion_cost_policy_does_not_treat_unknown_reservations_as_measured_savings():
    from factory.evaluation import can_promote

    # Policy-unit inputs, not modifications to persisted evaluation results or scores.
    candidate = {
        "total": 10,
        "critical_failures": 0,
        "metrics": {"safety": 1, "approval_compliance": 1},
        "mean_latency_ms": 10,
        "cost": 0.1,
        "score": 1,
        "splits": {},
        "reserved_cost": 0.2,
    }
    baseline = {**candidate, "cost": 0.5, "reserved_cost": 0}
    assert not can_promote(candidate, policy={"maximum_evaluation_cost": 0.25})
    assert not can_promote(candidate, baseline, {"objective": "cost"})
    assert can_promote({**candidate, "reserved_cost": 0}, baseline, {"objective": "cost"})
