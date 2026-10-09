import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from factory.db import now
from factory.deployment_runtime import enqueue
from factory.models import Approval, BusinessRecord, Deployment, Invocation, RuntimeJob
from factory.runtime import execute, resolve_approval
from factory.security import Principal


@pytest.mark.asyncio
@pytest.mark.parametrize("same_request", [False, True])
async def test_concurrent_approvals_serialize_inventory_and_incoming_request(db, seeded, same_request):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Production row locking requires PostgreSQL")
    org, user, _, version, *_ = seeded
    actor = Principal(user.id, org.id, "admin")
    inputs = (
        {"text": "Harbor Bistro: 1 kg Rice", "request_id": "duplicate-incoming"}
        if same_request
        else {"text": "Harbor Bistro: 3 cases Eggs"}
    )
    runs = [await execute(db, version, inputs) for _ in range(2)]
    approvals = [db.scalar(select(Approval).where(Approval.run_id == run.id)).id for run in runs]
    db.commit()
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    barrier = Barrier(2)

    def approve(approval_id):
        with sessions() as session:
            approval = session.get(Approval, approval_id)
            barrier.wait(timeout=10)
            try:
                asyncio.run(resolve_approval(session, approval, actor, True))
                session.commit()
                return "applied"
            except ValueError as error:
                session.rollback()
                return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, approvals))
    assert results.count("applied") == 1, results
    assert any(("Duplicate incoming" if same_request else "Inventory changed") in result for result in results)
    db.expire_all()
    assert (
        db.scalar(
            select(func.count()).select_from(BusinessRecord).where(BusinessRecord.key.in_([run.id for run in runs]))
        )
        == 1
    )
    sku = "SKU-004" if same_request else "SKU-010"
    product = db.scalar(select(BusinessRecord).where(BusinessRecord.org_id == org.id, BusinessRecord.key == sku))
    assert product.data["stock"] == (299 if same_request else 1)


def test_concurrent_idempotent_enqueue_reserves_only_one_invocation(db, seeded):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Production row locking requires PostgreSQL")
    org, user, agent, version, *_ = seeded
    version.approved_at = now()
    version.approved_by = user.id
    deployment = Deployment(org_id=org.id, agent_id=agent.id, version_id=version.id, active=True)
    db.add(deployment)
    db.commit()
    actor = Principal(user.id, org.id, "admin")
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    barrier = Barrier(2)

    def invoke(_):
        with sessions() as session:
            barrier.wait(timeout=10)
            run, job = enqueue(session, deployment.id, actor, {"text": "Harbor Bistro: 2 kg Rice"}, "same-key")
            session.commit()
            return run.id, job.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, range(2)))
    assert results[0] == results[1]
    assert db.scalar(select(func.count()).select_from(Invocation).where(Invocation.deployment_id == deployment.id)) == 1
    assert db.scalar(select(func.count()).select_from(RuntimeJob).where(RuntimeJob.org_id == org.id)) == 1
