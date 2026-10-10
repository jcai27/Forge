"""Builder-written tools: static policy, sandbox protocol, and the capability path through the runtime.

The sandbox server in these tests runs on the host as an owned test fixture. It proves the protocol,
the in-language policy and the broker boundary. Container isolation (no network, no host disk, limits)
is proved separately by scripts/test-sandbox.sh against the real image.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
from agents import Model, ModelResponse, Usage
from fastapi.testclient import TestClient
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from sqlalchemy import select

from factory.api import app, limits
from factory.builder import apply_patch, persist_version
from factory.codepolicy import CodePolicyError, check, code_hash
from factory.config import settings
from factory.connectors import discover_connection
from factory.db import get_db, uid
from factory.evaluation import evaluate_case
from factory.models import Approval, Connection, EvaluationCase, EvaluationRun, ToolDefinition
from factory.runtime import execute, reconstruct_agent
from factory.sandbox import GeneratedToolError, SandboxUnavailable, run_generated_tool
from factory.schemas import AgentSpec, GeneratedTool, SpecPatch
from factory.security import encrypt, token_for

REPO = Path(__file__).resolve().parents[3]

COUNT = """
def run(input, call):
    rows = call("records", {"collection": input["collection"]})["records"]
    return {"count": len(rows)}
"""


@pytest.fixture(scope="module")
def sandbox_socket():
    directory = tempfile.mkdtemp(prefix="sbx")
    path = os.path.join(directory, "s.sock")
    server = subprocess.Popen(
        [sys.executable, "-I", str(REPO / "services/sandbox/server.py"), path],
        env={"SANDBOX_POLICY_DIR": str(REPO / "apps/api/factory")},
    )
    try:
        for _ in range(100):
            if os.path.exists(path):
                try:
                    with httpx.Client(transport=httpx.HTTPTransport(uds=path), base_url="http://sandbox") as client:
                        if client.get("/health").status_code == 200:
                            break
                except httpx.HTTPError:
                    pass
            time.sleep(0.05)
        else:
            raise RuntimeError("sandbox test fixture did not start")
        yield path
    finally:
        server.kill()
        server.wait()


@pytest.fixture
def sandbox(sandbox_socket, monkeypatch):
    monkeypatch.setattr(settings(), "sandbox_socket", sandbox_socket)
    return sandbox_socket


async def no_capabilities(alias, arguments):
    raise AssertionError("no capability expected")


ALLOWED = """
import re
from decimal import Decimal, ROUND_HALF_UP

UNITS = {"kilograms": "kg"}


def normalise(unit):
    return UNITS.get(unit, unit)


def run(input, call):
    match = re.search(r"(\\d+(?:\\.\\d+)?)\\s*(\\w+)", input["text"])
    quantity = Decimal(match.group(1)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"quantity": str(quantity), "unit": normalise(match.group(2))}
"""


def test_policy_accepts_ordinary_parsing_code():
    check(ALLOWED)
    assert len(code_hash(ALLOWED)) == 64


@pytest.mark.parametrize(
    "code",
    [
        "import os\ndef run(input, call):\n    return {}\n",
        "import sys\ndef run(input, call):\n    return {}\n",
        "import subprocess\ndef run(input, call):\n    return {}\n",
        "import socket\ndef run(input, call):\n    return {}\n",
        "from json import codecs\ndef run(input, call):\n    return {}\n",
        "from operator import attrgetter\ndef run(input, call):\n    return {}\n",
        "from . import x\ndef run(input, call):\n    return {}\n",
        "def run(input, call):\n    return {'x': ().__class__}\n",
        "def run(input, call):\n    return {'x': call.__globals__}\n",
        "def run(input, call):\n    return {'x': (i for i in []).gi_frame}\n",
        "def run(input, call):\n    return {'x': '{0.a}'.format(input)}\n",
        "def run(input, call):\n    try:\n        return {}\n    except:\n        return {}\n",
        "def run(input, call):\n    with input:\n        return {}\n",
        "class A:\n    pass\ndef run(input, call):\n    return {}\n",
        "def run(input, call):\n    global x\n    return {}\n",
        "async def run(input, call):\n    return {}\n",
        "def run(input):\n    return {}\n",
        "def run(input, call, extra=1):\n    return {}\n",
        "def helper(input, call):\n    return {}\n",
        "def run(input, call):\n    return {}\nrun({}, None)\n",
        "def run(input, call):\n    __import__('os')\n    return {}\n",
        "def run(input, call):\n    return {'x': input.__dict__}\n",
        "def run(input, call)\n    return {}\n",
        "x = 1\n" * 30000,
        "",
    ],
)
def test_policy_rejects_code_outside_the_vocabulary(code):
    with pytest.raises(CodePolicyError):
        check(code)


@pytest.mark.asyncio
async def test_sandbox_runs_code_and_replays_capabilities_deterministically(sandbox):
    seen = []

    async def broker(alias, arguments):
        seen.append((alias, arguments))
        return {"records": [{"sku": "A"}, {"sku": "B"}, {"sku": "C"}]}

    assert await run_generated_tool(COUNT, {"collection": "products"}, broker) == {"count": 3}
    assert seen == [("records", {"collection": "products"})]
    assert await run_generated_tool(ALLOWED, {"text": "2.5 kilograms rice"}, no_capabilities) == {
        "quantity": "2.50",
        "unit": "kg",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,expected",
    [
        ("    return {'x': open('/etc/passwd').read()}", "NameError"),
        ("    return {'x': str(eval('1'))}", "NameError"),
        ("    return {'x': str(getattr(input, 'keys'))}", "NameError"),
        ("    return {'x': str(type(input))}", "NameError"),
        ("    import json\n    return {'x': str(json.codecs)}", "AttributeError"),
        ("    import statistics\n    return {'x': str(statistics.sys)}", "AttributeError"),
        ("    return [1, 2]", "JSON object"),
        ("    return {'x': {1, 2}}", "JSON object"),
        ("    return {'x': 'y' * 400000}", "size limit"),
        ("    raise ValueError('boom')", "ValueError: boom"),
        ("    return {'x': 1 / 0}", "ZeroDivisionError"),
        ("    while True:\n        pass", "without a result"),
        ("    def f(n):\n        return f(n + 1)\n    return {'x': f(0)}", "RecursionError"),
    ],
)
async def test_sandbox_contains_misbehaving_code(sandbox, body, expected):
    with pytest.raises(GeneratedToolError, match=expected):
        await run_generated_tool("def run(input, call):\n" + body + "\n", {}, no_capabilities)


@pytest.mark.asyncio
async def test_capability_loop_is_bounded_and_cannot_be_dodged(sandbox):
    calls = []

    async def broker(alias, arguments):
        calls.append(arguments)
        return {"n": arguments["n"]}

    greedy = "def run(input, call):\n    for n in range(50):\n        call('x', {'n': n})\n    return {}\n"
    with pytest.raises(GeneratedToolError, match="(?i)too many"):
        await run_generated_tool(greedy, {}, broker)
    assert len(calls) == 8
    # Swallowing the stop signal does not let a tool continue without the real answer.
    swallow = (
        "def run(input, call):\n    try:\n        value = call('x', {'n': 1})\n"
        "    finally:\n        return {'answered': False}\n"
    )
    calls.clear()
    assert await run_generated_tool(swallow, {}, broker) == {"answered": False}
    assert calls == [{"n": 1}], "the capability was still performed exactly once"
    # A tool whose requests differ between runs is stopped rather than trusted.
    shifty = (
        "from datetime import datetime\n"
        "def run(input, call):\n    call('x', {'n': 1})\n"
        "    return call('x', {'n': datetime.now().microsecond + 2})\n"
    )
    with pytest.raises(GeneratedToolError, match="changed a capability request"):
        await run_generated_tool(shifty, {}, broker)

    async def failing(alias, arguments):
        raise RuntimeError("upstream unavailable")

    handled = "def run(input, call):\n    try:\n        call('x', {})\n    except ValueError as error:\n        return {'handled': str(error)}\n"
    assert await run_generated_tool(handled, {}, failing) == {"handled": "RuntimeError: upstream unavailable"}

    async def denied(alias, arguments):
        raise PermissionError("not yours")

    with pytest.raises(PermissionError):
        await run_generated_tool(handled, {}, denied)


@pytest.mark.asyncio
async def test_without_a_sandbox_generated_code_is_never_run(monkeypatch):
    monkeypatch.setattr(settings(), "sandbox_socket", "")
    with pytest.raises(SandboxUnavailable):
        await run_generated_tool(COUNT, {"collection": "products"}, no_capabilities)
    monkeypatch.setattr(settings(), "sandbox_socket", "/nonexistent/sandbox.sock")
    with pytest.raises(SandboxUnavailable):
        await run_generated_tool(COUNT, {"collection": "products"}, no_capabilities)


def message(payload):
    return ResponseOutputMessage(
        type="message",
        role="assistant",
        id=uid(),
        status="completed",
        content=[ResponseOutputText(type="output_text", text=json.dumps(payload), annotations=[])],
    )


class CallsOneTool(Model):
    """Local provider transport: call the named tool once, then answer with its result."""

    def __init__(self, tool_name, arguments, final=None):
        self.tool_name, self.arguments, self.final = tool_name, arguments, final
        self.tool_names, self.tool_output = [], None

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        items = input if isinstance(input, list) else []
        self.tool_names = [tool.name for tool in tools]
        outputs = [i["output"] for i in items if isinstance(i, dict) and i.get("type") == "function_call_output"]
        if not outputs:
            output = [
                ResponseFunctionToolCall(
                    type="function_call",
                    name=self.tool_name,
                    arguments=json.dumps(self.arguments),
                    call_id=uid(),
                    id=uid(),
                )
            ]
        else:
            self.tool_output = json.loads(outputs[-1])
            output = [message(self.final(self.tool_output) if self.final else self.tool_output)]
        return ModelResponse(
            output=output, usage=Usage(requests=1, input_tokens=5, output_tokens=5, total_tokens=10), response_id=uid()
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


@pytest.fixture
def custom(db, seeded, monkeypatch):
    org, _, agent, initial, suite, connection = seeded
    read = db.scalar(
        select(ToolDefinition).where(
            ToolDefinition.connection_id == connection.id, ToolDefinition.name == "read_records"
        )
    )
    spec = AgentSpec.model_validate(initial.spec)
    agent.template = spec.template = "custom"
    spec.tools = [read.id]
    spec.output_schema = {"type": "object"}
    spec.generated_tools = [
        GeneratedTool(
            name="count_records",
            description="Count rows in a collection.",
            input_schema={
                "type": "object",
                "properties": {"collection": {"type": "string"}},
                "required": ["collection"],
            },
            output_schema={"type": "object", "required": ["count"], "properties": {"count": {"type": "integer"}}},
            code=COUNT,
            capabilities={"records": read.id},
        )
    ]
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr(settings(), "execution_mode", "live")

    def install(model):
        def bind(context, mode):
            built = reconstruct_agent(context, mode)
            built.model = model
            return built

        monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)
        return model

    return org, agent, spec, suite, read, install


def test_persisting_generated_tools_enforces_scope_policy_and_secrets(db, custom):
    org, agent, spec, _, read, _ = custom
    version = persist_version(db, agent, spec)
    stored = version.spec["generated_tools"][0]
    assert stored["code_hash"] == code_hash(COUNT)
    tool = spec.generated_tools[0]

    tool.capabilities = {"records": uid()}
    with pytest.raises(PermissionError, match="outside this version"):
        persist_version(db, agent, spec)
    tool.capabilities = {"records": read.id}

    tool.code = "import os\ndef run(input, call):\n    return {}\n"
    with pytest.raises(ValueError, match="code policy"):
        persist_version(db, agent, spec)

    connection = db.scalar(select(Connection).where(Connection.org_id == org.id))
    connection.encrypted_secret = encrypt("tenant-credential-9f3a71c2")
    db.flush()
    tool.code = 'def run(input, call):\n    return {"t": "tenant-credential-9f3a71c2"}\n'
    with pytest.raises(PermissionError, match="credential"):
        persist_version(db, agent, spec)
    tool.code = 'API_KEY = "abc123"\ndef run(input, call):\n    return {}\n'
    with pytest.raises(PermissionError, match="credential"):
        persist_version(db, agent, spec)

    tool.code = COUNT
    spec.generated_tools = [tool, tool.model_copy()]
    with pytest.raises(ValueError, match="distinct"):
        persist_version(db, agent, spec)


def test_a_patch_can_add_a_generated_tool_but_not_widen_its_reach(db, custom):
    _, agent, spec, _, read, _ = custom
    spec.generated_tools = []
    parent = persist_version(db, agent, spec)
    tool = GeneratedTool(name="count_records", description="Count rows.", code=COUNT, capabilities={"records": read.id})
    candidate = apply_patch(AgentSpec.model_validate(parent.spec), SpecPatch(generated_tools=[tool]))
    assert candidate.tools == parent.spec["tools"], "a generated tool adds code, never a new registered tool"
    assert persist_version(db, agent, candidate).spec["generated_tools"][0]["code_hash"] == code_hash(COUNT)


@pytest.mark.asyncio
async def test_generated_tool_runs_through_the_permission_checked_tool_path(db, custom, sandbox):
    _, agent, spec, _, read, install = custom
    version = persist_version(db, agent, spec)
    model = install(CallsOneTool("g_count_records", {"collection": "products"}))
    run = await execute(db, version, {"text": "How many products?"})
    assert run.status == "completed", run.error
    assert run.output == {"count": 100}
    assert "g_count_records" in model.tool_names
    # The capability went through the ordinary registered tool, and both steps are traced.
    assert run.metrics["tool_sequence"] == ["read_records", "generated:count_records"]
    assert run.metrics["tool_calls"] == 2


@pytest.mark.asyncio
async def test_tampered_code_or_undeclared_capability_is_a_safety_failure(db, custom, sandbox):
    _, agent, spec, _, read, install = custom
    version = persist_version(db, agent, spec)
    install(CallsOneTool("g_count_records", {"collection": "products"}))
    # Code changed after the version was pinned no longer matches its hash.
    tampered = json.loads(json.dumps(version.spec))
    tampered["generated_tools"][0]["code"] = COUNT.replace("len(rows)", "len(rows) + 1")
    version.spec = tampered
    db.flush()
    run = await execute(db, version, {"text": "How many products?"})
    assert run.status == "failed" and run.metrics["safety_violations"] == 1

    spec.generated_tools[0].code = 'def run(input, call):\n    return call("other", {})\n'
    undeclared = persist_version(db, agent, spec)
    run = await execute(db, undeclared, {"text": "How many products?"})
    assert run.status == "failed" and run.metrics["safety_violations"] == 1
    assert run.metrics["tool_sequence"] == []


@pytest.mark.asyncio
async def test_generated_tool_failure_is_reported_to_the_model_not_raised(db, custom, sandbox):
    _, agent, spec, _, _, install = custom
    spec.generated_tools[0].code = "def run(input, call):\n    raise ValueError('cannot parse')\n"
    version = persist_version(db, agent, spec)
    model = install(CallsOneTool("g_count_records", {"collection": "products"}, final=lambda out: {"saw": out}))
    run = await execute(db, version, {"text": "How many products?"})
    assert run.status == "completed", run.error
    assert model.tool_output == {"error": "ValueError: cannot parse"}


@pytest.mark.asyncio
async def test_generated_tool_write_capability_is_staged_never_executed(db, custom, sandbox, monkeypatch):
    org, agent, spec, suite, read, install = custom
    email = Connection(
        org_id=org.id,
        name="Mail",
        kind="email",
        config={"provider": "mock"},
        permissions={"read": True, "write": True},
        status="connected",
    )
    db.add(email)
    db.flush()
    await discover_connection(db, email)
    send = db.scalar(
        select(ToolDefinition).where(ToolDefinition.connection_id == email.id, ToolDefinition.name == "send_email")
    )
    spec.connection_ids = [*spec.connection_ids, email.id]
    spec.tools = [read.id, send.id]
    spec.generated_tools = [
        GeneratedTool(
            name="notify_ops",
            description="Send a notification.",
            code=(
                "def run(input, call):\n"
                '    return call("send", {"to": "ops@example.invalid", "subject": "Count", "body": input["body"]})\n'
            ),
            capabilities={"send": send.id},
        )
    ]
    version = persist_version(db, agent, spec)
    install(CallsOneTool("g_notify_ops", {"body": "hello"}))

    def forbidden(*args, **kwargs):
        raise AssertionError("a generated tool must never reach a connector for a write")

    monkeypatch.setattr("factory.runtime.adapter", forbidden)
    run = await execute(db, version, {"text": "Notify operations"})
    assert run.status == "waiting_for_approval", (run.status, run.error)
    approval = db.scalar(select(Approval).where(Approval.run_id == run.id))
    assert approval.status == "pending" and approval.action["tool_id"] == send.id
    assert run.output["requires_approval"] is True and run.output["status"] == "staged"

    # In evaluation the same write is refused outright.
    case = EvaluationCase(
        org_id=org.id,
        suite_id=suite.id,
        name="Notify",
        split="development",
        input={"text": "Notify operations"},
        assertions=[],
    )
    evaluation = EvaluationRun(org_id=org.id, version_id=version.id, suite_id=suite.id)
    db.add_all([case, evaluation])
    db.flush()
    result = await evaluate_case(db, evaluation, version, case)
    assert not result.passed and "safety" in result.failures


@pytest.mark.asyncio
async def test_run_fails_closed_when_no_sandbox_is_configured(db, custom, monkeypatch):
    _, agent, spec, _, _, install = custom
    monkeypatch.setattr(settings(), "sandbox_socket", "")
    version = persist_version(db, agent, spec)
    install(CallsOneTool("g_count_records", {"collection": "products"}))
    run = await execute(db, version, {"text": "How many products?"})
    assert run.status == "failed" and run.error == "SandboxUnavailable"


def test_approval_requires_acknowledging_each_new_piece_of_generated_code(db, seeded, custom, monkeypatch):
    org, agent, spec, _, _, _ = custom
    user = seeded[1]
    version = persist_version(db, agent, spec)
    db.commit()
    monkeypatch.setattr("factory.api.quality_gate", lambda db, version: {})  # isolate the code-review gate
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
            refused = client.post(f"/versions/{version.id}/approve")
            assert refused.status_code == 409
            assert refused.json()["error"]["code"] == "code_review_required"
            listed = refused.json()["error"]["generated_tools"]
            assert listed == [
                {"name": "count_records", "code_hash": code_hash(COUNT), "capabilities": {"records": "read_records"}}
            ]
            wrong = client.post(f"/versions/{version.id}/approve", json={"acknowledged_code": ["0" * 64]})
            assert wrong.status_code == 409
            accepted = client.post(f"/versions/{version.id}/approve", json={"acknowledged_code": [code_hash(COUNT)]})
            assert accepted.status_code == 200 and accepted.json()["approved_at"]
            # The same code in a later version was already reviewed; changed code is not.
            same = persist_version(db, agent, spec)
            db.commit()
            assert client.post(f"/versions/{same.id}/approve").status_code == 200
            spec.generated_tools[0].code = COUNT.replace("len(rows)", "len(rows) * 1")
            changed = persist_version(db, agent, spec)
            db.commit()
            assert client.post(f"/versions/{changed.id}/approve").status_code == 409
    finally:
        app.dependency_overrides.clear()
