import pytest
from sqlalchemy import select

from factory.builder import design, persist_version
from factory.evaluation import evaluate_suite
from factory.fixtures import seed_suite
from factory.models import AgentRecord, Approval, BusinessRecord
from factory.runtime import execute, resolve_approval
from factory.security import Principal


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "template,text,expected_collection",
    [("quotes", "Harbor Bistro: 3 kg Tomatoes", "quotes"), ("hiring", "Schedule Alex Rivera", "communications")],
)
async def test_additional_templates_use_shared_factory_and_approval(db, seeded, template, text, expected_collection):
    org, user, original, _, _, connection = seeded
    agent = AgentRecord(org_id=org.id, project_id=original.project_id, name=template, request=text, template=template)
    db.add(agent)
    db.flush()
    spec = await design(db, agent, [connection.id])
    version = persist_version(db, agent, spec)
    suite = seed_suite(db, agent)
    evaluation = await evaluate_suite(db, version, suite)
    assert evaluation.scorecard["score"] == 1, evaluation.scorecard
    run = await execute(db, version, {"text": text})
    assert run.status == "waiting_for_approval"
    if template == "quotes":
        assert run.output["total_cents"] == 1002
    else:
        assert run.output["candidate_id"] == "CAN-001"
    approval = db.scalar(select(Approval).where(Approval.run_id == run.id))
    await resolve_approval(db, approval, Principal(user.id, org.id, "admin"), True)
    assert db.scalar(
        select(BusinessRecord).where(BusinessRecord.collection == expected_collection, BusinessRecord.key == run.id)
    )
