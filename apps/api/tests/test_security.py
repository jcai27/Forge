import pytest
from sqlalchemy import select

from factory.models import Approval, BusinessRecord, Connection, ToolDefinition
from factory.runtime import BudgetHooks, execute, resolve_approval
from factory.schemas import AgentSpec
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


@pytest.mark.asyncio
async def test_uncertain_external_dispatch_never_retries_and_requires_reconciliation(db, seeded, monkeypatch):
    from fastapi.testclient import TestClient

    from factory.api import app, limits
    from factory.builder import persist_version
    from factory.connectors import discover_connection
    from factory.db import get_db
    from factory.models import ExecutionRun, ToolDefinition
    from factory.security import token_for

    org, user, agent, initial, _, _ = seeded
    connection = Connection(
        org_id=org.id,
        name="Mock email",
        kind="email",
        config={"provider": "mock"},
        permissions={"read": True, "write": True},
        status="connected",
    )
    db.add(connection)
    db.flush()
    await discover_connection(db, connection)
    definition = db.scalar(
        select(ToolDefinition).where(ToolDefinition.connection_id == connection.id, ToolDefinition.name == "send_email")
    )
    spec = AgentSpec.model_validate(initial.spec)
    spec.connection_ids.append(connection.id)
    spec.tools.append(definition.id)
    version = persist_version(db, agent, spec)
    run = ExecutionRun(org_id=org.id, version_id=version.id, mode="demo", input={}, status="waiting_for_approval")
    db.add(run)
    db.flush()
    approval = Approval(
        org_id=org.id,
        run_id=run.id,
        action={
            "kind": "connector",
            "connection_id": connection.id,
            "version_id": version.id,
            "tool_id": definition.id,
            "arguments": {
                "to": "candidate@example.invalid",
                "subject": "Interview",
                "body": "Confirm your availability",
            },
        },
    )
    db.add(approval)
    db.commit()
    calls = []

    class Provider:
        async def invoke(self, name, arguments):
            calls.append(arguments)
            raise TimeoutError("Unknown provider receipt")

    monkeypatch.setattr("factory.runtime.adapter", lambda *args, **kwargs: Provider())
    actor = Principal(user.id, org.id, "admin")
    await resolve_approval(db, approval, actor, True)
    assert approval.status == "reconciliation_required"
    await resolve_approval(db, approval, actor, True)
    assert len(calls) == 1
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
            response = client.post(
                f"/approvals/{approval.id}/reconcile",
                json={"outcome": "applied", "receipt": "Provider message receipt MSG-001 independently confirmed"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "completed"
            assert (
                client.post(
                    f"/approvals/{approval.id}/reconcile",
                    json={"outcome": "applied", "receipt": "Provider receipt confirmed again"},
                ).status_code
                == 409
            )
    finally:
        app.dependency_overrides.clear()
    assert len(calls) == 1
