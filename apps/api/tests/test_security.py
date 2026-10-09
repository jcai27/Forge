import pytest
from sqlalchemy import select

from factory.models import Approval, BusinessRecord, ToolDefinition
from factory.runtime import BudgetHooks, execute, resolve_approval
from factory.security import Principal


@pytest.mark.asyncio
async def test_contract_mutation_and_revocation_fail_closed(db, seeded):
    _, _, _, version, _, connection = seeded
    definition = db.get(ToolDefinition, version.spec["tools"][0])
    definition.definition = {**definition.definition, "description": "Changed contract"}
    run = await execute(db, version, {"text": "Harbor Bistro: 2 kg Rice"})
    assert run.status == "failed"
    assert run.error == "PermissionError"
    definition.definition = version.spec["tool_contracts"][definition.id]
    connection.status = "revoked"
    run = await execute(db, version, {"text": "Harbor Bistro: 2 kg Rice"})
    assert run.status == "failed"
    assert not db.scalar(select(Approval).where(Approval.run_id == run.id))


@pytest.mark.asyncio
async def test_connection_permissions_rechecked_at_approval(db, seeded):
    org, user, _, version, _, connection = seeded
    run = await execute(db, version, {"text": "Harbor Bistro: 2 kg Rice"})
    approval = db.scalar(select(Approval).where(Approval.run_id == run.id))
    connection.permissions = {"read": True, "write": False}
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await resolve_approval(db, approval, Principal(user.id, org.id, "admin"), True)
    assert not db.scalar(select(BusinessRecord).where(BusinessRecord.key == run.id))


@pytest.mark.asyncio
async def test_live_budget_rejects_call_before_spending():
    hook = BudgetHooks(0, "live")
    from agents import Agent

    with pytest.raises(ValueError, match="Insufficient"):
        await hook.on_llm_start(None, Agent(name="Test"), "instructions", [{"role": "user", "content": "request"}])
    assert hook.cost == 0
