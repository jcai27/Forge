import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from agents import Agent, ModelResponse, Usage
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from factory.config import settings
from factory.db import now
from factory.fixtures import business_snapshot
from factory.models import Approval, BuildJob, EvaluationCase, ExecutionRun, ToolDefinition, UsageRecord
from factory.provider_accounting import BuildInterrupted, recover_reservations
from factory.runtime import DeterministicToolModel, execute, tool_name
from factory.schemas import Budget
from factory.workflow import control, new_job


def setup_evaluation(db, seeded):
    org, _, agent, version, suite, _ = seeded
    case = db.scalar(
        select(EvaluationCase).where(
            EvaluationCase.suite_id == suite.id, EvaluationCase.name == "Exact product Tomatoes"
        )
    )
    definition = db.scalar(
        select(ToolDefinition).where(ToolDefinition.org_id == org.id, ToolDefinition.name == "prepare_operation")
    )
    job = new_job(db, agent, Budget())
    job.state = "TESTING"
    db.commit()
    return version, case, job, tool_name(definition)


class EvaluationProvider(DeterministicToolModel):
    """Explicit local SDK contract: real registered tool dispatch with reported usage."""

    def __init__(self, tool_name, input_data, callback=None):
        super().__init__(tool_name, input_data)
        self.callback, self.calls = callback, 0

    async def get_response(self, *args, **kwargs):
        self.calls += 1
        if self.callback:
            observed = self.callback()
            if inspect.isawaitable(observed):
                await observed
        items = kwargs.get("input", args[1] if len(args) > 1 else [])
        for item in items:
            if isinstance(item, dict) and item.get("role") == "user" and isinstance(item.get("content"), str):
                self.input_data = json.loads(item["content"])
        response = await super().get_response(*args, **kwargs)
        return ModelResponse(
            output=response.output,
            response_id=response.response_id,
            usage=Usage(requests=1, input_tokens=20, output_tokens=10, total_tokens=30),
        )


def install_provider(monkeypatch, provider):
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "explicit-local-evaluation-contract")
    monkeypatch.setattr("factory.runtime.Agent", lambda **kwargs: Agent(**{**kwargs, "model": provider}))


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [None, "pause", "cancel", "lease_transfer", "provider_error"])
async def test_evaluation_commits_before_dispatch_settles_once_and_checks_control_before_tools(
    db, seeded, monkeypatch, action
):
    version, case, job, tool_name = setup_evaluation(db, seeded)
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    before = business_snapshot(db, version.org_id)

    def during_dispatch():
        with sessions() as other:
            record = other.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
            assert record.role == "evaluation_agent" and record.status == "pending" and record.reserved_cost > 0
            assert record.cost == record.tokens == 0
            pending_run = other.get(ExecutionRun, record.run_id)
            assert pending_run.status == "running" and pending_run.metrics["reserved_cost"] == record.reserved_cost
            observed = other.get(BuildJob, job.id)
            assert observed.spent == record.reserved_cost
            if action == "lease_transfer":
                observed.lease_owner = "another-worker"
            elif action in ("pause", "cancel"):
                control(other, observed, action)
            other.commit()
        if action == "provider_error":
            raise RuntimeError("Explicit simulated evaluation transport failure")

    provider = EvaluationProvider(tool_name, case.input, during_dispatch)
    install_provider(monkeypatch, provider)
    if action in ("pause", "cancel", "lease_transfer"):
        with pytest.raises(BuildInterrupted):
            await execute(db, version, case.input, evaluation=True, job=job)
    else:
        run = await execute(db, version, case.input, evaluation=True, job=job)
        assert run.status == ("failed" if action else "completed")
        if action is None:
            assert run.output["lines"][0]["sku"] == "SKU-001" and run.output["total_cents"] == 900
            assert run.metrics["tool_calls"] == 1 and run.metrics["build_accounted_cost"] == run.metrics["cost"]
            assert run.metrics["execution_duration_ms"] == run.metrics["duration_ms"] > 0
    db.expire_all()
    record = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
    run = db.get(ExecutionRun, record.run_id)
    assert provider.calls == 1 and business_snapshot(db, version.org_id) == before
    assert list(db.scalars(select(Approval).where(Approval.org_id == version.org_id))) == []
    if action == "provider_error":
        assert record.status == "uncertain" and record.tokens == record.cost == 0
        assert job.spent == run.metrics["reserved_cost"] == record.reserved_cost > 0
    else:
        assert record.status == "recorded" and record.tokens == 30 and record.reserved_cost == 0
        assert job.spent == pytest.approx(record.cost) and run.metrics["cost"] == record.cost
        if action:
            assert run.metrics["tool_calls"] == 0
            assert job.state == {"pause": "PAUSED", "cancel": "CANCELLED", "lease_transfer": "TESTING"}[action]


@pytest.mark.asyncio
async def test_evaluation_provider_http_failure_does_not_retry_or_lose_charge(db, seeded, monkeypatch):
    version, case, job, _ = setup_evaluation(db, seeded)
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(
            500, json={"error": {"message": "Explicit local evaluation failure", "type": "server_error"}}
        )

    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "explicit-local-evaluation-http-contract")
    monkeypatch.setattr(
        "factory.builder.AsyncOpenAI",
        lambda **kwargs: AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))),
    )
    run = await execute(db, version, case.input, evaluation=True, job=job)
    record = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
    assert len(requests) == 1 and run.status == "failed" and run.error == "InternalServerError"
    assert record.status == "uncertain" and job.spent == record.reserved_cost > 0
    assert record.tokens == record.cost == 0


@pytest.mark.asyncio
async def test_evaluation_process_kill_retains_reservation_and_bounds_next_attempt(db, seeded, tmp_path, monkeypatch):
    version, case, job, tool_name = setup_evaluation(db, seeded)
    marker = tmp_path / "evaluation-dispatch"
    environment = {
        **os.environ,
        "DATABASE_URL": db.get_bind().url.render_as_string(hide_password=False),
        "EXECUTION_MODE": "live",
        "OPENAI_API_KEY": "explicit-local-evaluation-no-network",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    schema = db.get_bind().get_execution_options().get("schema_translate_map", {}).get(None)
    if schema:
        environment["TEST_SCHEMA"] = schema
    helper = Path(__file__).parent / "helpers" / "crash_evaluation.py"
    process = subprocess.Popen(
        [sys.executable, str(helper), case.id, job.id, str(marker)],
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
            time.sleep(0.02)
        assert marker.exists()
        process.kill()
        process.communicate(timeout=5)
        db.expire_all()
        record = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
        reservation = record.reserved_cost
        assert record.status == "pending" and job.spent == reservation > 0
        recover_reservations(db, job)
        job.lease_until = now()
        job.budget = {**job.budget, "max_cost": reservation * 1.5}
        db.commit()
        interrupted = db.get(ExecutionRun, record.run_id)
        assert interrupted.status == "failed" and interrupted.error == "InterruptedProviderCall"
        assert record.status == "uncertain" and record.tokens == record.cost == 0
        provider = EvaluationProvider(tool_name, case.input)
        install_provider(monkeypatch, provider)
        run = await execute(db, version, case.input, evaluation=True, job=job, max_cost=reservation * 0.5)
        assert run.status == "failed" and run.error == "BudgetExceeded" and provider.calls == 0
        assert job.spent == reservation
        assert len(list(db.scalars(select(UsageRecord).where(UsageRecord.job_id == job.id)))) == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_standalone_evaluation_records_run_owned_usage_without_build_charge(db, seeded, monkeypatch):
    version, case, job, tool_name = setup_evaluation(db, seeded)
    install_provider(monkeypatch, EvaluationProvider(tool_name, case.input))
    run = await execute(db, version, case.input, evaluation=True)
    record = db.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
    assert run.status == "completed" and record.role == "evaluation_agent" and record.job_id is None
    assert record.status == "recorded" and record.tokens == run.metrics["tokens"] == 30
    assert job.spent == 0 and run.metrics["cost"] == record.cost


@pytest.mark.asyncio
@pytest.mark.parametrize("pause", [False, True])
async def test_worker_evaluation_checkpoint_does_not_charge_observed_usage_twice(db, seeded, monkeypatch, pause):
    from factory.models import EvaluationResult
    from factory.workflow import start_evaluation, worker_tick

    version, case, job, tool_name = setup_evaluation(db, seeded)
    suite = seeded[4]
    start_evaluation(db, job, version, suite)
    db.commit()
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)

    def during_dispatch():
        if pause:
            with sessions() as other:
                control(other, other.get(BuildJob, job.id), "pause")
                other.commit()

    install_provider(monkeypatch, EvaluationProvider(tool_name, case.input, during_dispatch))
    assert await worker_tick(sessions)
    db.expire_all()
    record = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
    assert record.status == "recorded" and job.spent == pytest.approx(record.cost)
    assert job.state == ("PAUSED" if pause else "TESTING") and job.lease_owner is None
    results = list(
        db.scalars(
            select(EvaluationResult).where(EvaluationResult.evaluation_run_id == job.checkpoint["evaluation_id"])
        )
    )
    assert len(results) == (0 if pause else 1)


@pytest.mark.asyncio
async def test_build_hooks_cannot_commit_production_execution_transactions(db, seeded, monkeypatch):
    version, case, job, tool_name = setup_evaluation(db, seeded)
    provider = EvaluationProvider(tool_name, case.input)
    install_provider(monkeypatch, provider)
    with pytest.raises(ValueError, match="isolated evaluation"):
        await execute(db, version, case.input, job=job)
    assert provider.calls == 0 and job.spent == 0
    assert list(db.scalars(select(UsageRecord).where(UsageRecord.job_id == job.id))) == []
