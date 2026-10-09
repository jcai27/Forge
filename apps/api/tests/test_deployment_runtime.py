import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from factory.api import app, limits
from factory.config import settings
from factory.db import get_db, now
from factory.deployment_runtime import enqueue, execute_job, invocation_tick, schedule_tick
from factory.models import Approval, BusinessRecord, Deployment, DeploymentTrigger, Invocation, Membership, RuntimeJob
from factory.runtime import resolve_approval
from factory.security import Principal, token_for


@pytest.fixture
def deployment(db, seeded):
    org, user, agent, version, *_ = seeded
    version.approved_at = now()
    version.approved_by = user.id
    deployment = Deployment(
        org_id=org.id,
        agent_id=agent.id,
        version_id=version.id,
        active=True,
        policy={"max_cost": 1, "lifetime_max_cost": 10, "max_invocations": 1000},
    )
    db.add(deployment)
    db.commit()
    return deployment


@pytest.fixture
def client(db, seeded):
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    org, user, *_ = seeded
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_schedule_creates_durable_idempotent_invocation_without_business_write(client, db, seeded, deployment):
    org, user, *_ = seeded
    result = client.post(
        f"/deployments/{deployment.id}/triggers",
        json={
            "name": "Daily order",
            "kind": "schedule",
            "interval_seconds": 60,
            "input": {"text": "Harbor Bistro: 2 kg Rice"},
        },
    )
    assert result.status_code == 201, result.text
    trigger = db.get(DeploymentTrigger, result.json()["id"])
    trigger.next_run_at = now() - timedelta(seconds=1)
    db.commit()
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    assert schedule_tick(sessions)
    assert not schedule_tick(sessions)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Invocation).where(Invocation.deployment_id == deployment.id)) == 1
    assert await invocation_tick(sessions)
    db.expire_all()
    job = db.scalar(select(RuntimeJob).where(RuntimeJob.org_id == org.id))
    assert job.state == "COMPLETED"
    invocation = db.get(Invocation, job.invocation_id)
    approval = db.scalar(select(Approval).where(Approval.run_id == invocation.run_id))
    assert approval and approval.status == "pending"
    assert not db.scalar(select(BusinessRecord).where(BusinessRecord.key == invocation.run_id))
    await resolve_approval(db, approval, Principal(user.id, org.id, "admin"), True)
    assert db.scalar(select(BusinessRecord).where(BusinessRecord.key == invocation.run_id))


@pytest.mark.asyncio
async def test_signed_invocation_webhook_deduplicates_and_keeps_write_pending(client, db, deployment):
    secret = "unique-webhook-signing-key"
    result = client.post(
        f"/deployments/{deployment.id}/triggers", json={"name": "Signed orders", "kind": "webhook", "secret": secret}
    )
    assert result.status_code == 201, result.text
    assert secret not in result.text
    endpoint = "/deployment-webhooks/" + result.json()["id"]
    timestamp = str(int(time.time()))
    body = json.dumps({"input": {"text": "Harbor Bistro: 2 kg Tomatoes"}, "idempotency_key": "event-1"}).encode()
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"X-Webhook-Timestamp": timestamp, "X-Webhook-Signature": signature}
    assert client.post(endpoint, content=body).status_code == 401
    first = client.post(endpoint, content=body, headers=headers)
    assert first.status_code == 202, first.text
    again = client.post(endpoint, content=body, headers=headers)
    assert again.json()["run_id"] == first.json()["run_id"]
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    await invocation_tick(sessions)
    db.expire_all()
    assert db.scalar(select(Approval).where(Approval.run_id == first.json()["run_id"])).status == "pending"
    assert not db.scalar(select(BusinessRecord).where(BusinessRecord.key == first.json()["run_id"]))
    disabled = client.patch("/deployment-triggers/" + result.json()["id"], json={"enabled": False})
    assert disabled.status_code == 200
    assert client.post(endpoint, content=body, headers=headers).status_code == 404


@pytest.mark.asyncio
async def test_queue_rechecks_authorization_and_pause(db, seeded, deployment):
    org, user, *_ = seeded
    actor = Principal(user.id, org.id, "admin")
    run, job = enqueue(db, deployment.id, actor, {"text": "Harbor Bistro: 2 kg Rice"}, "queued-1")
    db.commit()
    member = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.org_id == org.id))
    member.role = "viewer"
    db.commit()
    await execute_job(db, job.id)
    assert run.status == "failed"
    assert not db.scalar(select(Approval).where(Approval.run_id == run.id))
    member.role = "admin"
    db.commit()
    run, job = enqueue(db, deployment.id, actor, {"text": "Harbor Bistro: 2 kg Rice"}, "queued-2")
    db.commit()
    deployment.active = False
    db.commit()
    await execute_job(db, job.id)
    assert run.status == "failed"
    assert deployment.reserved == 0


def test_lifetime_invocation_and_cost_budgets(db, seeded, deployment, monkeypatch):
    org, user, *_ = seeded
    actor = Principal(user.id, org.id, "admin")
    deployment.policy = {**deployment.policy, "max_invocations": 1, "lifetime_max_cost": 1}
    monkeypatch.setattr(settings(), "execution_mode", "live")
    run, job = enqueue(db, deployment.id, actor, {"text": "Harbor Bistro: 2 kg Rice"}, "once")
    db.commit()
    assert deployment.reserved == 1
    assert enqueue(db, deployment.id, actor, run.input, "once")[0].id == run.id
    with pytest.raises(HTTPException) as error:
        enqueue(db, deployment.id, actor, {"text": "Harbor Bistro: 3 kg Rice"}, "once")
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        enqueue(db, deployment.id, actor, run.input, "twice")
    assert error.value.status_code == 409
    deployment.policy = {**deployment.policy, "max_invocations": 5}
    with pytest.raises(HTTPException) as error:
        enqueue(db, deployment.id, actor, run.input, "over-lifetime-cost")
    assert "lifetime cost" in error.value.detail


@pytest.mark.asyncio
async def test_paused_deployment_blocks_pending_business_approval(db, seeded, deployment):
    org, user, *_ = seeded
    actor = Principal(user.id, org.id, "admin")
    run, job = enqueue(db, deployment.id, actor, {"text": "Harbor Bistro: 2 kg Rice"}, "pause-after-run")
    db.commit()
    await execute_job(db, job.id)
    approval = db.scalar(select(Approval).where(Approval.run_id == run.id))
    deployment.active = False
    db.commit()
    with pytest.raises(PermissionError, match="paused"):
        await resolve_approval(db, approval, actor, True)
    assert approval.status == "pending"
    assert not db.scalar(select(BusinessRecord).where(BusinessRecord.key == run.id))
