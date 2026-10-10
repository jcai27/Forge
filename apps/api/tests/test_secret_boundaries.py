import base64
import json
from urllib.parse import quote

import pytest
from agents import Model, ModelResponse, Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from sqlalchemy import select

from factory.api import serialize
from factory.builder import persist_version
from factory.connectors import discover_connection
from factory.db import uid
from factory.models import Connection, ExecutionEvent, Organization, ToolDefinition
from factory.runtime import execute, reconstruct_agent
from factory.schemas import AgentSpec
from factory.security import encrypt, known_secret_values, redact_tenant


def test_known_credentials_are_filtered_by_value_encoding_and_tenant(db, seeded):
    org, _, _, _, _, connection = seeded
    password = "fictional-password:/ + unicode-é"
    connection.encrypted_secret = encrypt(json.dumps({"username": "service-user", "password": password}))
    other = Organization(name="Other secret owner")
    db.add(other)
    db.flush()
    foreign = "foreign-tenant-fixture-credential"
    db.add(Connection(org_id=other.id, name="Other", kind="rest", encrypted_secret=encrypt(foreign)))
    db.commit()
    forms = [
        password,
        quote(password, safe=""),
        base64.b64encode(password.encode()).decode(),
        base64.b64encode(("service-user:" + password).encode()).decode(),
    ]
    payload = {"note": " | ".join(forms), "nested": [password], password: "value", "other": foreign}
    safe = redact_tenant(db, org.id, payload)
    for form in forms:
        assert form not in json.dumps(safe, ensure_ascii=False)
    assert safe["other"] == foreign and foreign not in known_secret_values(db, org.id)
    assert payload["nested"] == [password]  # No mutation of connector-owned state.
    assert serialize(connection)["has_secret"] is True


def test_revocation_keeps_historical_filtering_but_removes_dispatch_credentials(db, seeded):
    from fastapi.testclient import TestClient

    from factory.api import app, limits
    from factory.db import get_db
    from factory.models import SecretRedactionEntry
    from factory.security import token_for

    org, user, *_ = seeded
    secret = "fictional-retired-credential-in-historical-note"
    connection = Connection(
        org_id=org.id,
        name="Historical source",
        kind="email",
        config={"provider": "mock", "note": secret},
        encrypted_secret=encrypt(secret),
        permissions={"read": True},
        status="connected",
    )
    db.add(connection)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
            before = client.get(f"/integrations/{connection.id}")
            assert secret not in before.text
            revoked = client.post(f"/integrations/{connection.id}/revoke")
            assert revoked.status_code == 200 and secret not in revoked.text
            assert revoked.json()["has_secret"] is False
            assert client.post(f"/integrations/{connection.id}/revoke").status_code == 200
            assert secret not in client.get(f"/integrations/{connection.id}").text
        assert connection.encrypted_secret == "" and connection.status == "revoked"
        entry = db.scalar(select(SecretRedactionEntry).where(SecretRedactionEntry.connection_id == connection.id))
        assert entry is not None and secret not in entry.encrypted_secret
        assert secret in known_secret_values(db, org.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_sdk_tool_context_outputs_events_and_browser_rows_exclude_known_secrets(db, seeded, monkeypatch):
    org, _, agent, initial, *_ = seeded
    credential = "fictional-mail-password-hidden-in-normal-fields"
    encoded = base64.b64encode(credential.encode()).decode()
    email = Connection(
        org_id=org.id,
        name="Fixture email",
        kind="email",
        config={"provider": "mock", "fixtures": [{"subject": "Customer request", "body": credential + " " + encoded}]},
        encrypted_secret=encrypt(json.dumps({"username": "service@example.invalid", "password": credential})),
        permissions={"read": True},
        status="connected",
    )
    db.add(email)
    db.flush()
    await discover_connection(db, email)
    read = db.scalar(
        select(ToolDefinition).where(ToolDefinition.connection_id == email.id, ToolDefinition.name == "read_inbox")
    )
    spec = AgentSpec.model_validate(initial.spec)
    spec.template = "custom"
    spec.connection_ids, spec.tools = [email.id], [read.id]
    spec.instructions += " Notes: " + credential
    spec.output_schema = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
        "additionalProperties": False,
    }
    version = persist_version(db, agent, spec)
    calls = []

    class Provider(Model):
        async def get_response(
            self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
        ):
            visible = json.dumps(
                {
                    "system": system_instructions,
                    "input": input,
                    "tools": [t.params_json_schema for t in tools],
                    "schema": output_schema.json_schema(),
                }
            )
            assert credential not in visible and encoded not in visible
            calls.append(input)
            if len(calls) == 1:
                output = [
                    ResponseFunctionToolCall(
                        type="function_call",
                        name="t_" + read.id.replace("-", "_"),
                        arguments="{}",
                        call_id=uid(),
                        id=uid(),
                    )
                ]
            else:
                response = json.loads(
                    next(
                        item["output"]
                        for item in input
                        if isinstance(item, dict) and item.get("type") == "function_call_output"
                    )
                )
                assert "[REDACTED]" in response["messages"][0]["body"]
                # An adversarial fixture response cannot publish even a guessed secret.
                output = [
                    ResponseOutputMessage(
                        type="message",
                        role="assistant",
                        id=uid(),
                        status="completed",
                        content=[
                            ResponseOutputText(
                                type="output_text",
                                text=json.dumps({"summary": response["messages"][0]["body"] + credential}),
                                annotations=[],
                            )
                        ],
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

    def build(context, mode):
        result = reconstruct_agent(context, "demo") if mode == "demo" else reconstruct_agent(context, "live")
        result.model = Provider()
        return result

    from factory.config import settings

    monkeypatch.setattr(settings(), "openai_api_key", "explicit-local-sdk-fixture")
    monkeypatch.setattr("factory.runtime.reconstruct_agent", build)
    run = await execute(db, version, {"text": "Read request notes " + credential}, mode="live")
    assert run.status == "completed", run.error
    assert len(calls) == 2 and run.metrics["tokens"] == 40
    assert "[REDACTED]" in run.output["summary"]
    events = list(db.scalars(select(ExecutionEvent).where(ExecutionEvent.run_id == run.id)))
    for value in [
        run.input,
        run.output,
        [event.payload for event in events],
        serialize(run),
        serialize(email),
        serialize(version),
    ]:
        text = json.dumps(value, ensure_ascii=False)
        assert credential not in text and encoded not in text


@pytest.mark.asyncio
async def test_authorized_connector_receipt_is_sanitized_before_persistence(db, seeded, monkeypatch):
    from factory.models import Approval, ExecutionRun
    from factory.runtime import resolve_approval
    from factory.security import Principal

    org, user, agent, initial, *_ = seeded
    credential = "fictional-receipt-password-not-for-browser"
    connection = Connection(
        org_id=org.id,
        name="Receipt email",
        kind="email",
        config={"provider": "mock"},
        encrypted_secret=encrypt(credential),
        permissions={"read": True, "write": True},
        status="connected",
    )
    db.add(connection)
    db.flush()
    await discover_connection(db, connection)
    send = db.scalar(
        select(ToolDefinition).where(ToolDefinition.connection_id == connection.id, ToolDefinition.name == "send_email")
    )
    spec = AgentSpec.model_validate(initial.spec)
    spec.connection_ids, spec.tools = [connection.id], [send.id]
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
            "tool_id": send.id,
            "version_id": version.id,
            "arguments": {"to": "operator@example.invalid", "subject": "Receipt", "body": "Confirmed"},
        },
    )
    db.add(approval)
    db.commit()
    calls = []

    class Receipt:
        async def invoke(self, name, arguments):
            calls.append((name, arguments))
            return {"accepted": True, "note": "Provider echoed " + credential}

    monkeypatch.setattr("factory.runtime.adapter", lambda *args, **kwargs: Receipt())
    await resolve_approval(db, approval, Principal(user.id, org.id, "admin"), True)
    db.commit()
    db.expire_all()
    assert run.status == "completed" and approval.status == "approved" and len(calls) == 1
    assert credential not in json.dumps(run.output) and "[REDACTED]" in run.output["note"]
