"""Owned SDK provider contracts; no live OpenAI calls or production writes."""

import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_evaluation_accounting import EvaluationProvider, install_provider

from factory.config import settings
from factory.db import now
from factory.deployment_runtime import enqueue, execute_job
from factory.fixtures import business_snapshot
from factory.models import (
    AgentVersion,
    Approval,
    Deployment,
    ExecutionRun,
    Membership,
    RuntimeJob,
    ToolDefinition,
    UsageRecord,
)
from factory.runtime import tool_name
from factory.security import Principal


def setup_invocation(db, seeded, monkeypatch):
    org, user, agent, version, *_ = seeded
    version.approved_at = now()
    deployment = Deployment(
        org_id=org.id,
        agent_id=agent.id,
        version_id=version.id,
        active=True,
        policy={"max_cost": 1, "lifetime_max_cost": 10, "max_invocations": 1000},
    )
    db.add(deployment)
    db.commit()
    monkeypatch.setattr(settings(), "execution_mode", "live")
    run, job = enqueue(
        db,
        deployment.id,
        Principal(user.id, org.id, "admin"),
        {"text": "Harbor Bistro: 2 kg Tomatoes"},
        "ledger-contract",
    )
    db.commit()
    tool = db.scalar(
        select(ToolDefinition).where(ToolDefinition.org_id == org.id, ToolDefinition.name == "prepare_operation")
    )
    return deployment, run, job, tool_name(tool)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [None, "pause", "revoke", "unapprove", "budget", "lease_transfer", "provider_error"])
async def test_deployment_reserves_before_dispatch_and_preserves_control(db, seeded, monkeypatch, action):
    deployment, run, job, tool_name = setup_invocation(db, seeded, monkeypatch)
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    before = business_snapshot(db, run.org_id)

    def during_dispatch():
        with sessions() as other:
            record = other.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
            assert record.role == "deployment_agent" and record.status == "pending"
            assert record.reserved_cost > 0 and record.tokens == record.cost == 0
            observed_run = other.get(ExecutionRun, run.id)
            assert observed_run.status == "running" and observed_run.metrics["reserved_cost"] == record.reserved_cost
            observed_job = other.get(RuntimeJob, job.id)
            assert observed_job.lease_owner and observed_job.reservation == 1
            assert other.get(Deployment, deployment.id).reserved == 1
            assert list(other.scalars(select(Approval).where(Approval.run_id == run.id))) == []
            if action == "pause":
                other.get(Deployment, deployment.id).active = False
            elif action == "unapprove":
                other.get(AgentVersion, run.version_id).approved_at = None
            elif action == "budget":
                observed_deployment = other.get(Deployment, deployment.id)
                observed_deployment.policy = {**observed_deployment.policy, "max_cost": 0}
            elif action == "revoke":
                member = other.scalar(
                    select(Membership).where(Membership.org_id == run.org_id, Membership.user_id == job.actor_id)
                )
                member.role = "viewer"
            elif action == "lease_transfer":
                observed_job.lease_owner = "new-worker"
            other.commit()
        if action == "provider_error":
            raise RuntimeError("Explicit local deployment provider failure")

    provider = EvaluationProvider(tool_name, run.input, during_dispatch)
    install_provider(monkeypatch, provider)
    result = await execute_job(db, job.id)
    db.expire_all()
    record = db.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
    assert provider.calls == 1 and business_snapshot(db, run.org_id) == before
    if action == "lease_transfer":
        assert result is None and job.lease_owner == "new-worker" and job.state == "RUNNING"
        assert deployment.reserved == 1 and deployment.spent == 0
    elif action == "provider_error":
        assert run.status == "failed" and job.state == "FAILED"
        assert record.status == "uncertain" and record.cost == record.tokens == 0
        assert deployment.reserved == run.metrics["reserved_cost"] == record.reserved_cost > 0
        assert deployment.spent == job.reservation == 0
    else:
        assert record.status == "recorded" and record.tokens == 30 and record.reserved_cost == 0
        assert deployment.spent == pytest.approx(record.cost) and deployment.reserved == job.reservation == 0
        assert run.status == ("failed" if action else "waiting_for_approval")
        assert job.state == ("FAILED" if action else "COMPLETED")
    approvals = list(db.scalars(select(Approval).where(Approval.run_id == run.id)))
    assert len(approvals) == (0 if action else 1)
    if action:
        assert run.metrics.get("tool_calls", 0) == 0


@pytest.mark.asyncio
async def test_deployment_http_failure_retains_unknown_charge_without_retry(db, seeded, monkeypatch):
    deployment, run, job, _ = setup_invocation(db, seeded, monkeypatch)
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(500, json={"error": {"message": "Local deployment failure", "type": "server_error"}})

    monkeypatch.setattr(settings(), "openai_api_key", "explicit-local-deployment-http-contract")
    monkeypatch.setattr(
        "factory.builder.AsyncOpenAI",
        lambda **kwargs: AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))),
    )
    await execute_job(db, job.id)
    record = db.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
    assert len(requests) == 1 and run.error == "InternalServerError" and job.state == "FAILED"
    assert record.status == "uncertain" and deployment.reserved == record.reserved_cost > 0
    assert record.cost == record.tokens == deployment.spent == job.reservation == 0


@pytest.mark.asyncio
async def test_deployment_process_kill_retains_unknown_charge_on_recovery(db, seeded, tmp_path, monkeypatch):
    deployment, run, job, tool_name = setup_invocation(db, seeded, monkeypatch)
    marker = tmp_path / "deployment-dispatch"
    environment = {
        **os.environ,
        "DATABASE_URL": db.get_bind().url.render_as_string(hide_password=False),
        "EXECUTION_MODE": "live",
        "OPENAI_API_KEY": "explicit-local-deployment-no-network",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    schema = db.get_bind().get_execution_options().get("schema_translate_map", {}).get(None)
    if schema:
        environment["TEST_SCHEMA"] = schema
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent / "helpers" / "crash_deployment.py"), job.id, str(marker)],
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
        record = db.scalar(select(UsageRecord).where(UsageRecord.run_id == run.id))
        unknown = record.reserved_cost
        assert record.status == "pending" and unknown > 0 and deployment.reserved == job.reservation == 1
        job.lease_until = now() - timedelta(seconds=1)
        db.commit()
        provider = EvaluationProvider(tool_name, run.input)
        install_provider(monkeypatch, provider)
        await execute_job(db, job.id)
        db.expire_all()
        records = list(db.scalars(select(UsageRecord).where(UsageRecord.run_id == run.id)))
        assert len(records) == 2 and record.status == "uncertain" and record.reserved_cost == unknown
        assert provider.calls == 1 and job.attempts == 2 and job.state == "COMPLETED"
        assert deployment.reserved == run.metrics["reserved_cost"] == unknown
        assert deployment.spent == pytest.approx(run.metrics["cost"])
        assert deployment.spent > 0
        assert run.metrics["tokens"] == 30 and job.reservation == 0
        assert len(list(db.scalars(select(Approval).where(Approval.run_id == run.id)))) == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_late_response_settles_unknown_charge_without_republishing_stale_result(db, seeded, monkeypatch):
    deployment, run, job, tool_name = setup_invocation(db, seeded, monkeypatch)
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    successor = EvaluationProvider(tool_name, run.input)

    async def during_dispatch():
        with sessions() as other:
            claimed = other.get(RuntimeJob, job.id)
            claimed.lease_until = now() - timedelta(seconds=1)
            other.commit()
            install_provider(monkeypatch, successor)
            completed = await execute_job(other, job.id)
            assert completed.status == "waiting_for_approval"
            assert other.get(Deployment, deployment.id).reserved > 0

    original = EvaluationProvider(tool_name, run.input, during_dispatch)
    install_provider(monkeypatch, original)
    assert await execute_job(db, job.id) is None
    db.expire_all()
    records = list(db.scalars(select(UsageRecord).where(UsageRecord.run_id == run.id)))
    assert original.calls == successor.calls == 1 and len(records) == 2
    assert all(record.status == "recorded" and record.tokens == 30 for record in records)
    assert deployment.reserved == 0 and deployment.spent == pytest.approx(sum(record.cost for record in records))
    assert run.metrics["tokens"] == 60 and run.metrics["tool_calls"] == 1
    assert run.status == "waiting_for_approval" and job.state == "COMPLETED"
    assert len(list(db.scalars(select(Approval).where(Approval.run_id == run.id)))) == 1
