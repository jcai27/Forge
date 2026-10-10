import asyncio
import json

import pytest
from agents import Model, ModelResponse, Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from factory.builder import persist_version
from factory.config import settings
from factory.connectors import discover_connection
from factory.db import uid
from factory.fixtures import business_snapshot
from factory.models import Approval, Connection, ToolDefinition
from factory.runtime import execute, reconstruct_agent, resolve_approval, tool_name
from factory.schemas import AgentSpec
from factory.security import Principal


class WriteThenFinish(Model):
    """Explicit local SDK fixture; sends a tool request, never an external message."""

    def __init__(self, tool_name, after_tool, outcome):
        self.tool_name, self.after_tool, self.outcome, self.calls = tool_name, after_tool, outcome, 0

    async def get_response(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            output = [
                ResponseFunctionToolCall(
                    type="function_call",
                    name=self.tool_name,
                    arguments=json.dumps(
                        {
                            "to": "operator@example.invalid",
                            "subject": "Staging contract",
                            "body": "Fictional approval request",
                        }
                    ),
                    call_id=uid(),
                    id=uid(),
                )
            ]
        else:
            self.after_tool()
            if self.outcome == "error":
                raise RuntimeError("Explicit local provider failure after the tool request")
            if self.outcome == "timeout":
                await asyncio.sleep(1)
            payload = {"queued": True} if self.outcome == "valid" else {"wrong_field": True}
            output = [
                ResponseOutputMessage(
                    type="message",
                    role="assistant",
                    id=uid(),
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text=json.dumps(payload), annotations=[])],
                )
            ]
        return ModelResponse(
            output=output,
            usage=Usage(requests=1, input_tokens=10, output_tokens=10, total_tokens=20),
            response_id=uid(),
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["valid", "invalid", "error", "timeout"])
async def test_write_approvals_publish_only_after_validated_final_output(db, seeded, monkeypatch, outcome):
    org, user, agent, original, *_ = seeded
    connection = Connection(
        org_id=org.id,
        name="Explicit fictional email adapter",
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
    spec = AgentSpec.model_validate(original.spec)
    spec.template = "custom"
    spec.connection_ids, spec.tools = [connection.id], [definition.id]
    spec.input_schema = {"type": "object"}
    spec.output_schema = {
        "type": "object",
        "properties": {"queued": {"type": "boolean"}},
        "required": ["queued"],
        "additionalProperties": False,
    }
    version = persist_version(db, agent, spec)
    db.commit()
    before = business_snapshot(db, org.id)
    sessions = sessionmaker(db.get_bind(), expire_on_commit=False)
    checkpoints = []

    def after_tool():
        # Simulate a durable model checkpoint; incomplete approvals must not escape it.
        db.commit()
        with sessions() as other:
            assert list(other.scalars(select(Approval).where(Approval.org_id == org.id))) == []
        checkpoints.append(True)

    provider = WriteThenFinish(tool_name(definition), after_tool, outcome)

    def bind(context, mode):
        reconstructed = reconstruct_agent(context, mode)
        reconstructed.model = provider
        return reconstructed

    monkeypatch.setattr(settings(), "openai_api_key", "explicit-local-staging-contract")
    monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)
    dispatches = []

    class OwnedMockEmail:
        async def invoke(self, name, arguments):
            dispatches.append((name, arguments))
            return {"accepted": True, "mock": True}

    monkeypatch.setattr("factory.runtime.adapter", lambda *args, **kwargs: OwnedMockEmail())
    run = await execute(db, version, {}, mode="live", max_seconds=0.2 if outcome == "timeout" else None)
    db.commit()
    approvals = list(db.scalars(select(Approval).where(Approval.run_id == run.id)))
    assert checkpoints == [True] and provider.calls == 2
    assert dispatches == [] and business_snapshot(db, org.id) == before
    if outcome == "valid":
        assert run.status == "waiting_for_approval" and len(approvals) == 1
        assert run.metrics["approval_ids"] == [approvals[0].id]
        await resolve_approval(db, approvals[0], Principal(user.id, org.id, "admin"), True)
        assert len(dispatches) == 1 and run.status == "completed"
    else:
        assert run.status == "failed" and approvals == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "failed"])
@pytest.mark.parametrize("approved", [True, False])
async def test_approval_guard_blocks_incomplete_or_failed_execution(db, seeded, status, approved):
    org, user, _, version, *_ = seeded
    run = await execute(db, version, {"text": "Harbor Bistro: 2 kg Tomatoes"})
    approval = db.scalar(select(Approval).where(Approval.run_id == run.id))
    run.status = status
    db.commit()
    before = business_snapshot(db, org.id)
    if approved:
        with pytest.raises(PermissionError, match="valid decision checkpoint"):
            await resolve_approval(db, approval, Principal(user.id, org.id, "admin"), True)
        assert approval.status == "pending"
    else:
        await resolve_approval(db, approval, Principal(user.id, org.id, "admin"), False)
        assert approval.status == "rejected"
    assert business_snapshot(db, org.id) == before
