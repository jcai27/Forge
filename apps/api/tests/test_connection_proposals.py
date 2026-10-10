"""Connection proposals: drafts grant nothing; an administrator confirms hosts, supplies the secret and approves."""

import json
import socket

import httpx
import pytest
from agents import Agent, Model, ModelResponse, Usage
from fastapi.testclient import TestClient
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from sqlalchemy import func, select

from factory.api import app, limits
from factory.config import settings
from factory.db import get_db, uid
from factory.evaluation import development_evidence, evaluate_suite
from factory.models import (
    AgentVersion,
    BuildJob,
    Connection,
    ConnectionProposal,
    Membership,
    Organization,
    ToolDefinition,
    User,
)
from factory.proposals import ProposalError, check_rest_config, openapi_to_config
from factory.schemas import Budget
from factory.security import decrypt, passwords, token_for
from factory.workflow import advance, new_job

ORDERS = {
    "name": "list_orders",
    "description": "List recent orders.",
    "path": "/v1/orders",
    "method": "GET",
    "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}, "additionalProperties": False},
    "output_schema": {"type": "object", "required": ["orders"], "properties": {"orders": {"type": "array"}}},
}
CREATE = {
    "name": "create_order",
    "description": "Create an order.",
    "path": "/v1/orders",
    "method": "POST",
    "input_schema": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]},
    "output_schema": {"type": "object"},
}


def config(*operations, **overrides):
    return {
        "base_url": "https://api.vendor.example",
        "allowed_hosts": ["api.vendor.example"],
        "operations": list(operations or [ORDERS]),
        **overrides,
    }


def test_static_checks_accept_a_sound_draft_and_contact_nothing():
    samples = [{"operation": "list_orders", "arguments": {"limit": 5}, "response": {"orders": []}}]
    checks = check_rest_config(config(ORDERS, CREATE), samples)
    assert checks == {
        "static": "passed",
        "host": "api.vendor.example",
        "operations": 2,
        "write_operations": ["create_order"],
        "samples_checked": 1,
        "contacted": False,
    }


@pytest.mark.parametrize(
    "draft,samples",
    [
        (config(base_url="http://api.vendor.example"), ()),
        (config(base_url="https://user:pass@api.vendor.example"), ()),
        (config(base_url="https://api.vendor.example?key=1"), ()),
        (config(allowed_hosts=["api.vendor.example", "evil.example"]), ()),
        (config(allowed_hosts=["evil.example"]), ()),
        (config({**ORDERS, "path": "/v1/orders/{id}"}), ()),
        (config({**ORDERS, "path": "//evil.example/x"}), ()),
        (config({**ORDERS, "path": "/v1/../admin"}), ()),
        (config({**ORDERS, "path": "/v1/orders?all=1"}), ()),
        (config({**ORDERS, "method": "TRACE"}), ()),
        (config({**ORDERS, "name": "Bad Name"}), ()),
        (config(ORDERS, ORDERS), ()),
        (config({**ORDERS, "input_schema": {"type": "nope"}}), ()),
        (config({**ORDERS, "headers": {"X": "y"}}), ()),
        (config(health_path="https://evil.example/"), ()),
        (config(api_key="sk-live-123"), ()),
        (config(authorization="Bearer x"), ()),
        (config(*[{**ORDERS, "name": f"operation_{n}"} for n in range(41)]), ()),
        ({"base_url": "https://api.vendor.example", "allowed_hosts": ["api.vendor.example"], "operations": []}, ()),
        (config(), [{"operation": "list_orders", "arguments": {}, "response": {"wrong": 1}}]),
        (config(), [{"operation": "missing", "arguments": {}, "response": {}}]),
    ],
)
def test_static_checks_reject_unsafe_or_inconsistent_drafts(draft, samples):
    with pytest.raises(ProposalError):
        check_rest_config(draft, samples)


def test_openapi_import_is_deterministic_and_reports_what_it_skips():
    document = {
        "openapi": "3.0.3",
        "servers": [{"url": "https://api.vendor.example/base"}],
        "components": {
            "schemas": {
                "Order": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]},
                "OrderList": {
                    "type": "object",
                    "properties": {"orders": {"type": "array", "items": {"$ref": "#/components/schemas/Order"}}},
                },
            }
        },
        "paths": {
            "/v1/orders": {
                "get": {
                    "operationId": "listOrders",
                    "summary": "List orders",
                    "parameters": [{"name": "limit", "in": "query", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/OrderList"}}}}
                    },
                },
                "post": {
                    "operationId": "createOrder",
                    "requestBody": {
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Order"}}}
                    },
                    "responses": {"201": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                },
            },
            "/v1/orders/{id}": {"get": {"operationId": "getOrder", "responses": {"200": {}}}},
            "/v1/names": {
                "get": {
                    "operationId": "listNames",
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "array"}}}}},
                }
            },
            "/v1/upload": {
                "post": {
                    "operationId": "upload",
                    "requestBody": {"content": {"multipart/form-data": {"schema": {"type": "object"}}}},
                    "responses": {"200": {}},
                }
            },
        },
    }
    draft, skipped = openapi_to_config(document)
    assert draft["base_url"] == "https://api.vendor.example/base" and draft["allowed_hosts"] == ["api.vendor.example"]
    names = {operation["name"]: operation for operation in draft["operations"]}
    assert set(names) == {"listorders", "createorder"}
    assert names["listorders"]["input_schema"]["required"] == ["limit"]
    assert names["listorders"]["output_schema"]["properties"]["orders"]["items"]["required"] == ["sku"]
    assert names["createorder"]["method"] == "POST" and names["createorder"]["input_schema"]["required"] == ["sku"]
    assert {entry["operation"] for entry in skipped} == {"GET /v1/orders/{id}", "GET /v1/names", "POST /v1/upload"}
    assert check_rest_config(draft)["write_operations"] == ["createorder"]
    assert openapi_to_config(document) == (draft, skipped)
    with pytest.raises(ProposalError):
        openapi_to_config({"openapi": "3.0.0", "servers": [{"url": "http://plain.example"}], "paths": {}})
    with pytest.raises(ProposalError):
        openapi_to_config({"swagger": "2.0"})


@pytest.fixture
def vendor(monkeypatch):
    """Owned transport standing in for the vendor. Records what the connector sends at activation."""
    state = {"requests": [], "status": 200}

    def handler(request):
        state["requests"].append(request)
        return httpx.Response(state["status"], json={"orders": []})

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(
        "factory.connectors.pinned_client",
        lambda url, hosts, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs),
    )
    return state


@pytest.fixture
def http(db, seeded):
    org, user, *_ = seeded
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
        yield client
    app.dependency_overrides.clear()


def as_member(db, org, role):
    user = User(email=f"{role}-{uid()}@example.invalid", password_hash=passwords.hash("test-password"))
    db.add(user)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role=role))
    db.commit()
    return {"Authorization": "Bearer " + token_for(user.id, org.id)}


def test_a_draft_creates_no_connection_and_holds_no_secret(db, seeded, http, vendor):
    org, _, agent, *_ = seeded
    before = db.scalar(select(func.count()).select_from(Connection))
    created = http.post(
        "/connection-proposals",
        json={
            "name": "Vendor orders",
            "config": config(ORDERS, CREATE),
            "rationale": "Needs live orders",
            "agent_id": agent.id,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "proposed" and body["connection_id"] is None
    assert body["checks"]["contacted"] is False and body["checks"]["write_operations"] == ["create_order"]
    assert db.scalar(select(func.count()).select_from(Connection)) == before
    assert vendor["requests"] == [], "drafting must not contact the vendor"
    assert http.get("/connection-proposals").json()["total"] == 1
    # Credentials are refused in a draft; they belong only to approval.
    leaked = http.post("/connection-proposals", json={"name": "Bad", "config": config(api_key="sk-live-123")})
    assert leaked.status_code == 422 and "sk-live-123" not in leaked.text


def test_only_an_administrator_can_approve_and_must_confirm_the_exact_hosts(db, seeded, http, vendor):
    org, *_ = seeded
    proposal = http.post("/connection-proposals", json={"name": "Vendor", "config": config()}).json()
    path = f"/connection-proposals/{proposal['id']}/approve"
    approve = {"secret": "vendor-token-123456", "confirmed_hosts": ["api.vendor.example"]}
    editor = as_member(db, org, "editor")
    assert (
        http.post(
            "/connection-proposals", json={"name": "Editor draft", "config": config()}, headers=editor
        ).status_code
        == 201
    )
    assert http.post(path, json=approve, headers=editor).status_code == 403
    for hosts in ([], ["evil.example"], ["api.vendor.example", "evil.example"]):
        wrong = http.post(path, json={**approve, "confirmed_hosts": hosts})
        assert wrong.status_code == 409, wrong.text
    assert vendor["requests"] == []
    assert db.scalar(select(func.count()).select_from(Connection).where(Connection.name == "Vendor")) == 0


def test_approval_activates_the_connection_with_an_encrypted_secret(db, seeded, http, vendor):
    proposal = http.post("/connection-proposals", json={"name": "Vendor", "config": config(ORDERS, CREATE)}).json()
    approved = http.post(
        f"/connection-proposals/{proposal['id']}/approve",
        json={"secret": "vendor-token-123456", "confirmed_hosts": ["api.vendor.example"], "attach": False},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert "vendor-token-123456" not in approved.text
    assert body["proposal"]["status"] == "approved" and body["connection"]["status"] == "connected"
    assert body["connection"]["has_secret"] is True and body["connection"]["permissions"] == {
        "read": True,
        "write": False,
    }
    connection = db.get(Connection, body["connection"]["id"])
    assert decrypt(connection.encrypted_secret) == "vendor-token-123456"
    # The credential went only to the approved host, at activation.
    assert len(vendor["requests"]) == 1
    assert vendor["requests"][0].url.host == "api.vendor.example"
    assert vendor["requests"][0].headers["authorization"] == "Bearer vendor-token-123456"
    tools = {
        t.name: t.write for t in db.scalars(select(ToolDefinition).where(ToolDefinition.connection_id == connection.id))
    }
    assert tools == {"list_orders": False, "create_order": True}
    row = db.get(ConnectionProposal, proposal["id"])
    assert "vendor-token-123456" not in json.dumps([row.config, row.checks, row.rationale])
    assert (
        http.post(
            f"/connection-proposals/{proposal['id']}/approve",
            json={"secret": "x", "confirmed_hosts": ["api.vendor.example"]},
        ).status_code
        == 409
    )


def test_failed_activation_keeps_nothing(db, seeded, http, vendor):
    vendor["status"] = 401
    proposal = http.post("/connection-proposals", json={"name": "Vendor", "config": config()}).json()
    failed = http.post(
        f"/connection-proposals/{proposal['id']}/approve",
        json={"secret": "wrong-token-123456", "confirmed_hosts": ["api.vendor.example"]},
    )
    assert failed.status_code == 502 and "wrong-token-123456" not in failed.text
    db.expire_all()
    assert db.get(ConnectionProposal, proposal["id"]).status == "proposed"
    assert db.scalar(select(func.count()).select_from(Connection).where(Connection.name == "Vendor")) == 0


def test_attaching_creates_a_fresh_version_and_restarts_evidence(db, seeded, http, vendor):
    org, _, agent, initial, _, _ = seeded
    job = new_job(db, agent, Budget())
    job.state = "OPTIMIZING"
    job.checkpoint = {**job.checkpoint, "best_scorecard": {"score": 0.5}, "best_version_id": initial.id}
    db.commit()
    proposal = http.post(
        "/connection-proposals", json={"name": "Vendor", "config": config(ORDERS, CREATE), "agent_id": agent.id}
    ).json()
    approved = http.post(
        f"/connection-proposals/{proposal['id']}/approve",
        json={"secret": "vendor-token-123456", "confirmed_hosts": ["api.vendor.example"]},
    ).json()
    version = db.get(AgentVersion, approved["version"]["id"])
    connection_id = approved["connection"]["id"]
    read = db.scalar(
        select(ToolDefinition).where(
            ToolDefinition.connection_id == connection_id, ToolDefinition.name == "list_orders"
        )
    )
    write = db.scalar(
        select(ToolDefinition).where(
            ToolDefinition.connection_id == connection_id, ToolDefinition.name == "create_order"
        )
    )
    assert version.id != initial.id and connection_id in version.spec["connection_ids"]
    # Write was not granted, so the write tool is not part of the version.
    assert read.id in version.spec["tools"] and write.id not in version.spec["tools"]
    assert set(initial.spec["tools"]) <= set(version.spec["tools"])
    assert version.approved_at is None, "a new capability needs fresh review"
    db.expire_all()
    job = db.get(BuildJob, job.id)
    assert job.state == "BUILDING" and job.checkpoint["version_id"] == version.id
    assert "best_scorecard" not in job.checkpoint, "old scorecards are never reused for a changed agent"
    assert job.checkpoint["redirections"][-1]["reason"] == "Connection approved: Vendor"


def test_proposals_are_tenant_scoped_and_can_be_rejected(db, seeded, http):
    proposal = http.post("/connection-proposals", json={"name": "Vendor", "config": config()}).json()
    other = Organization(name="Other tenant")
    db.add(other)
    db.flush()
    outsider = as_member(db, other, "admin")
    assert http.get("/connection-proposals", headers=outsider).json()["total"] == 0
    assert (
        http.post(
            f"/connection-proposals/{proposal['id']}/approve",
            json={"secret": "x", "confirmed_hosts": ["api.vendor.example"]},
            headers=outsider,
        ).status_code
        == 404
    )
    assert http.post(f"/connection-proposals/{proposal['id']}/reject", headers=outsider).status_code in (403, 404)
    rejected = http.post(f"/connection-proposals/{proposal['id']}/reject")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert (
        http.post(
            f"/connection-proposals/{proposal['id']}/approve",
            json={"secret": "x", "confirmed_hosts": ["api.vendor.example"]},
        ).status_code
        == 409
    )


def test_openapi_import_endpoint_creates_a_draft(db, seeded, http):
    document = {
        "openapi": "3.1.0",
        "servers": [{"url": "https://api.vendor.example"}],
        "paths": {
            "/v1/orders": {
                "get": {
                    "operationId": "list_orders",
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
            "/v1/orders/{id}": {"get": {"operationId": "get_order", "responses": {"200": {}}}},
        },
    }
    created = http.post("/connection-proposals/import-openapi", json={"name": "Imported", "document": document})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["origin"] == "openapi" and [o["name"] for o in body["config"]["operations"]] == ["list_orders"]
    assert body["checks"]["skipped"][0]["operation"] == "GET /v1/orders/{id}"


def message(payload):
    return ResponseOutputMessage(
        type="message",
        role="assistant",
        id=uid(),
        status="completed",
        content=[ResponseOutputText(type="output_text", text=json.dumps(payload), annotations=[])],
    )


def tool_call(tool, /, **arguments):
    return ResponseFunctionToolCall(
        type="function_call", name=tool, arguments=json.dumps(arguments), call_id=uid(), id=uid()
    )


class Scripted(Model):
    def __init__(self, steps):
        self.steps, self.outputs = list(steps), []

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        items = input if isinstance(input, list) else []
        self.outputs = [i["output"] for i in items if isinstance(i, dict) and i.get("type") == "function_call_output"]
        return ModelResponse(
            output=[self.steps.pop(0)],
            usage=Usage(requests=1, input_tokens=20, output_tokens=10, total_tokens=30),
            response_id=uid(),
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


@pytest.mark.asyncio
async def test_builder_can_draft_a_connection_but_gains_no_capability(db, seeded, monkeypatch):
    _, _, agent, initial, suite, _ = seeded
    evaluation = await evaluate_suite(db, initial, suite, ("development", "regression"))
    job = new_job(db, agent, Budget())
    job.state = "OPTIMIZING"
    job.checkpoint = {
        **job.checkpoint,
        "diagnosis": {"development_failures": development_evidence(db, evaluation)},
        "best_version_id": initial.id,
        "best_scorecard": evaluation.scorecard,
        "best_evaluation_id": evaluation.id,
    }
    db.commit()
    draft = {"name": "Vendor orders", "base_url": "https://api.vendor.example", "operations": [ORDERS]}
    builder = Scripted(
        [
            tool_call("propose_connection", **{**draft, "operations": [{**ORDERS, "path": "/v1/orders/{id}"}]}),
            tool_call(
                "propose_connection",
                **draft,
                rationale="The agent needs live order status",
                samples=[{"operation": "list_orders", "arguments": {}, "response": {"orders": []}}],
            ),
            tool_call("propose_connection", **draft),
            message({"hypothesis": "No change until the connection is approved"}),
        ]
    )
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": builder}))
    connections = db.scalar(select(func.count()).select_from(Connection))
    await advance(db, job)
    db.commit()
    assert job.state == "RETESTING", (job.state, job.error)
    assert "static relative path" in json.loads(builder.outputs[0])["error"]
    accepted = json.loads(builder.outputs[1])
    assert accepted["status"] == "proposed" and accepted["checks"]["samples_checked"] == 1
    assert "already been proposed" in json.loads(builder.outputs[2])["error"]
    rows = list(db.scalars(select(ConnectionProposal)))
    assert len(rows) == 1
    row = rows[0]
    assert (row.origin, row.status, row.agent_id, row.job_id) == ("builder", "proposed", agent.id, job.id)
    assert row.config["allowed_hosts"] == ["api.vendor.example"]
    # Nothing was connected and the new candidate has exactly the parent's reach.
    assert db.scalar(select(func.count()).select_from(Connection)) == connections
    candidate = db.get(AgentVersion, job.checkpoint["version_id"])
    assert candidate.spec["tools"] == initial.spec["tools"]
    assert candidate.spec["connection_ids"] == initial.spec["connection_ids"]


def test_openapi_import_survives_a_self_referencing_schema():
    document = {
        "openapi": "3.0.0",
        "servers": [{"url": "https://api.vendor.example"}],
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {"children": {"type": "array", "items": {"$ref": "#/components/schemas/Node"}}},
                }
            }
        },
        "paths": {
            "/v1/tree": {
                "get": {
                    "operationId": "get_tree",
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Node"}}}}
                    },
                }
            }
        },
    }
    draft, _ = openapi_to_config(document)
    assert len(json.dumps(draft)) < 20_000
    assert check_rest_config(draft)["operations"] == 1
