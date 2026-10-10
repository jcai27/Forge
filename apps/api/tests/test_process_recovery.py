import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select

from factory.models import BuildIteration, BuildJob, EvaluationResult
from factory.schemas import Budget
from factory.workflow import advance, new_job


@pytest.mark.asyncio
@pytest.mark.parametrize("limited_budget", [False, True])
async def test_factory_process_crash_retains_unknown_charge_and_bounds_retry(db, seeded, tmp_path, limited_budget):
    from factory.config import settings
    from factory.db import now
    from factory.models import AgentVersion, UsageRecord

    _, _, agent, *_ = seeded
    job = new_job(db, agent, Budget())
    job.state = "DESIGNING"
    db.commit()
    marker = tmp_path / "factory-dispatch"
    environment = {
        **os.environ,
        "DATABASE_URL": db.get_bind().url.render_as_string(hide_password=False),
        "WORKER_LEASE_SECONDS": "2",
        "EXECUTION_MODE": "live",
        "OPENAI_API_KEY": "explicit-local-contract-no-network",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    schema = db.get_bind().get_execution_options().get("schema_translate_map", {}).get(None)
    if schema:
        environment["TEST_SCHEMA"] = schema
    command = [sys.executable, str(Path(__file__).parent / "helpers" / "crash_factory.py"), job.id]
    process = subprocess.Popen(
        [*command, "interrupt", str(marker)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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
        original = db.scalar(select(UsageRecord).where(UsageRecord.job_id == job.id))
        reservation = original.reserved_cost
        assert original.status == "pending" and original.cost == original.tokens == 0
        assert reservation > 0 and db.get(BuildJob, job.id).spent == reservation
        # Expire the killed worker's lease without waiting through its request timeout.
        job.lease_until = now()
        if limited_budget:
            job.budget = {**job.budget, "max_cost": reservation * 1.5}
        db.commit()
        recovered = subprocess.run(
            [*command, "recover", str(marker)], env=environment, capture_output=True, text=True, timeout=20
        )
        assert recovered.returncode == 0, recovered.stderr
        db.expire_all()
        records = list(db.scalars(select(UsageRecord).where(UsageRecord.job_id == job.id)))
        assert db.get(UsageRecord, original.id).status == "uncertain"
        assert db.get(UsageRecord, original.id).reserved_cost == reservation
        if limited_budget:
            assert "BUDGET_EXHAUSTED 0" in recovered.stdout
            assert job.spent == reservation and len(records) == 1
            assert (
                db.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent.id)) == 1
            )
        else:
            assert "BUILDING 1" in recovered.stdout
            measured = next(record for record in records if record.status == "recorded")
            assert measured.tokens == 30 and measured.reserved_cost == 0
            assert job.spent == pytest.approx(reservation + 30 * settings().estimated_token_cost)
            assert (
                db.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent.id)) == 2
            )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_worker_process_crash_rolls_back_partial_trial_and_recovers(db, seeded, tmp_path):
    _, _, agent, *_ = seeded
    job = new_job(db, agent, Budget())
    db.commit()
    # Reach testing and commit exactly one evaluation trial before the interrupted process.
    for _ in range(5):
        await advance(db, job)
        db.commit()
    evaluation_id = job.checkpoint["evaluation_id"]
    committed = db.scalar(
        select(func.count()).select_from(EvaluationResult).where(EvaluationResult.evaluation_run_id == evaluation_id)
    )
    assert committed == 1
    marker = tmp_path / "worker-checkpoint"
    environment = {
        **os.environ,
        "DATABASE_URL": db.get_bind().url.render_as_string(hide_password=False),
        "WORKER_LEASE_SECONDS": "2",
        "EXECUTION_MODE": "demo",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    schema = db.get_bind().get_execution_options().get("schema_translate_map", {}).get(None)
    if schema:
        environment["TEST_SCHEMA"] = schema
    helper = Path(__file__).parent / "helpers" / "crash_worker.py"
    command = [sys.executable, str(helper), job.id]
    process = subprocess.Popen(
        [*command, "interrupt", str(marker)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                _, stderr = process.communicate()
                raise AssertionError(f"Worker unexpectedly exited: {stderr}")
            time.sleep(0.02)
        assert marker.exists(), "Worker never reached the interrupt checkpoint"
        process.kill()
        process.communicate(timeout=5)
        db.expire_all()
        # In-flight trial and its traces roll back; prior durable trial survives.
        assert (
            db.scalar(
                select(func.count())
                .select_from(EvaluationResult)
                .where(EvaluationResult.evaluation_run_id == evaluation_id)
            )
            == committed
        )
        assert db.get(BuildJob, job.id).lease_owner
        db.rollback()
        restarted = subprocess.run(
            [*command, "recover", str(marker)], env=environment, capture_output=True, text=True, timeout=20
        )
        assert restarted.returncode == 0, restarted.stderr
        assert "READY_FOR_REVIEW" in restarted.stdout
        db.expire_all()
        assert db.get(BuildJob, job.id).state == "READY_FOR_REVIEW"
        iterations = list(
            db.scalars(select(BuildIteration).where(BuildIteration.job_id == job.id).order_by(BuildIteration.number))
        )
        assert [i.number for i in iterations] == [1, 2, 3]
        # Authored development/regression trials run once in each committed iteration.
        assert (
            db.scalar(
                select(func.count())
                .select_from(EvaluationResult)
                .where(EvaluationResult.evaluation_run_id == evaluation_id)
            )
            == 28
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_runtime_process_crash_recovers_without_duplicate_approval_or_write(db, seeded, tmp_path):
    from factory.db import now
    from factory.deployment_runtime import enqueue
    from factory.models import Approval, BusinessRecord, Deployment, RuntimeJob
    from factory.security import Principal

    org, user, agent, version, *_ = seeded
    version.approved_at = now()
    version.approved_by = user.id
    deployment = Deployment(org_id=org.id, agent_id=agent.id, version_id=version.id, policy={"max_cost": 1})
    db.add(deployment)
    db.flush()
    run, job = enqueue(
        db, deployment.id, Principal(user.id, org.id, "admin"), {"text": "Harbor Bistro: 2 kg Rice"}, "recover-runtime"
    )
    db.commit()
    marker = tmp_path / "runtime-checkpoint"
    environment = {
        **os.environ,
        "DATABASE_URL": db.get_bind().url.render_as_string(hide_password=False),
        "WORKER_LEASE_SECONDS": "2",
        "EXECUTION_MODE": "demo",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    schema = db.get_bind().get_execution_options().get("schema_translate_map", {}).get(None)
    if schema:
        environment["TEST_SCHEMA"] = schema
    command = [sys.executable, str(Path(__file__).parent / "helpers" / "crash_runtime.py"), job.id]
    process = subprocess.Popen(
        [*command, "interrupt", str(marker)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                _, stderr = process.communicate()
                raise AssertionError(f"Runtime unexpectedly exited: {stderr}")
            time.sleep(0.02)
        assert marker.exists()
        process.kill()
        process.communicate(timeout=5)
        db.expire_all()
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.run_id == run.id)) == 0
        assert db.get(RuntimeJob, job.id).attempts == 1
        db.rollback()
        recovered = subprocess.run(
            [*command, "recover", str(marker)], env=environment, capture_output=True, text=True, timeout=20
        )
        assert recovered.returncode == 0, recovered.stderr
        assert "COMPLETED" in recovered.stdout
        db.expire_all()
        assert db.get(RuntimeJob, job.id).attempts == 2
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.run_id == run.id)) == 1
        assert not db.scalar(select(BusinessRecord).where(BusinessRecord.key == run.id))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
