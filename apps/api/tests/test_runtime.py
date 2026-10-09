import pytest
from sqlalchemy import select

from factory.evaluation import evaluate_suite
from factory.models import Approval, BusinessRecord, ExecutionEvent
from factory.runtime import execute, resolve_approval
from factory.security import Principal


@pytest.mark.asyncio
async def test_sdk_invokes_registered_tool_and_prepares_order(db, seeded):
    org, user, agent, version, suite, connection = seeded
    run = await execute(db, version, {"text": "Harbor Bistro: 2 kg Tomatoes"})
    assert run.status == "waiting_for_approval", run.error
    assert run.output["lines"][0]["sku"] == "SKU-001"
    assert run.output["total_cents"] == 900
    assert run.metrics["tokens"] == 0
    events = list(db.scalars(select(ExecutionEvent).where(ExecutionEvent.run_id == run.id)))
    assert [e.kind for e in events] == ["execution_started", "tool_started", "tool_completed", "execution_completed"]
    assert run.mode == "demo"
    assert not db.scalar(select(BusinessRecord).where(BusinessRecord.key == run.id))
    approval = db.scalar(select(Approval).where(Approval.run_id == run.id))
    await resolve_approval(db, approval, Principal(user.id, org.id, "admin"), True)
    assert db.scalar(select(BusinessRecord).where(BusinessRecord.key == run.id))
    await resolve_approval(db, approval, Principal(user.id, org.id, "admin"), True)
    assert len(list(db.scalars(select(BusinessRecord).where(BusinessRecord.key == run.id)))) == 1


@pytest.mark.asyncio
async def test_deficient_configuration_produces_measured_failures(db, seeded):
    _, _, _, version, suite, _ = seeded
    evaluation = await evaluate_suite(db, version, suite)
    assert 0 < evaluation.scorecard["score"] < 1
    assert evaluation.scorecard["metrics"]["safety"] == 1
    assert evaluation.scorecard["total"] >= 30
    assert evaluation.scorecard["critical_failures"] == 0, evaluation.scorecard
