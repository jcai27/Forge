"""Open-web research: pinned egress, bounded reads, and no tenant data in anything that leaves."""

import gzip
import json
import socket

import httpx
import pytest
from agents import Agent, Model, ModelResponse, Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from sqlalchemy import select

from factory.config import settings
from factory.db import uid
from factory.evaluation import development_evidence, evaluate_suite
from factory.models import AgentVersion, ExecutionEvent, UsageRecord
from factory.research import WITHHELD, OutboundScreen, WebGateway, html_to_text, research, tenant_markers
from factory.schemas import Budget
from factory.workflow import advance, new_job

PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def web(monkeypatch, handler):
    """Owned test transport in place of the pinned client; records every outbound request."""
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: PUBLIC)
    monkeypatch.setattr(
        "factory.research.pinned_client",
        lambda url, hosts, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(record), **kwargs),
    )
    return requests


class Body(httpx.AsyncByteStream):
    """A streamed body, as the real transport delivers one."""

    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        for start in range(0, len(self.data), 65536):
            yield self.data[start : start + 65536]


def page(body, kind="text/html", status=200, headers=None):
    return httpx.Response(status, content=body, headers={"Content-Type": kind, **(headers or {})})


def test_html_is_reduced_to_visible_text():
    markup = "<html><head><style>a{}</style><script>steal()</script></head><body><h1>Orders API</h1><p>Use  cents.</p></body></html>"
    assert html_to_text(markup) == "Orders API Use cents."


def test_tenant_markers_block_values_identifiers_and_phrases_but_not_general_questions():
    evidence = [
        {
            "case": "Alias order",
            "input": {"text": "Harbor Bistro: 2 kg chook", "customer_email": "chef@harbor.example"},
            "output": {"customer_id": "CUST-0042", "flags": ["missing_sku:chook"]},
        }
    ]
    screen = OutboundScreen({"tenant-credential-9f3a71c2"}, tenant_markers(evidence))
    for leaking in (
        "How should I parse Harbor Bistro: 2 kg chook",
        "who is chef@harbor.example",
        "lookup CUST-0042 in the ERP",
        "what does 2 kg chook mean",
        "is tenant-credential-9f3a71c2 a valid token",
        "https://docs.example/search?q=CUST-0042",
    ):
        assert not screen.allowed(leaking), leaking
    for general in (
        "How does the Acme ERP REST API paginate order lists?",
        "What unit does the Stripe API use for amounts?",
        "https://docs.example/api/orders",
    ):
        assert screen.allowed(general), general
    with pytest.raises(PermissionError):
        screen.check("lookup CUST-0042", "question")
    assert screen.refused == ["question"]


@pytest.mark.asyncio
async def test_gateway_fetches_text_and_sends_no_credentials(monkeypatch):
    requests = web(monkeypatch, lambda request: page(b"<p>Amounts are in <b>cents</b>.</p>"))
    gateway = WebGateway(OutboundScreen())
    result = await gateway.fetch("https://docs.example/api#section")
    assert result["text"] == "Amounts are in cents." and result["url"] == "https://docs.example/api"
    assert gateway.fetched == ["https://docs.example/api"]
    sent = requests[0]
    assert sent.method == "GET"
    assert "authorization" not in sent.headers and "cookie" not in sent.headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://docs.example/api",
        "https://user:pass@docs.example/api",
        "https://docs.example:8443/api",
        "ftp://docs.example/api",
        "file:///etc/passwd",
    ],
)
async def test_gateway_rejects_unsafe_urls_before_any_request(monkeypatch, url):
    requests = web(monkeypatch, lambda request: page(b"never"))
    with pytest.raises(ValueError):
        await WebGateway(OutboundScreen()).fetch(url)
    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1"])
async def test_gateway_uses_the_pinned_transport_which_refuses_private_addresses(monkeypatch, address):
    # The real pinned client is used here: resolution to a private address must fail before any socket.
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]
    )
    connected = []
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: connected.append(a))
    with pytest.raises(Exception) as error:
        await WebGateway(OutboundScreen()).fetch("https://internal.example/admin")
    assert "forbidden" in str(error.value).lower() or isinstance(error.value, (httpx.ConnectError, ValueError))
    assert connected == []


@pytest.mark.asyncio
async def test_redirects_are_revalidated_on_every_hop_and_bounded(monkeypatch):
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "https://other.example/final"})
        if request.url.path == "/to-http":
            return httpx.Response(302, headers={"Location": "http://other.example/plain"})
        if request.url.path == "/to-data":
            return httpx.Response(302, headers={"Location": "https://other.example/x?id=CUST-0042"})
        if request.url.path == "/loop":
            return httpx.Response(302, headers={"Location": "https://docs.example/loop"})
        return page(b"landed", "text/plain")

    requests = web(monkeypatch, handler)
    screen = OutboundScreen(markers={"cust-0042"})
    result = await WebGateway(screen).fetch("https://docs.example/start")
    assert result["url"] == "https://other.example/final" and result["text"] == "landed"
    with pytest.raises(ValueError, match="https"):
        await WebGateway(screen).fetch("https://docs.example/to-http")
    # A redirect cannot be used to smuggle a tenant value into a URL either.
    with pytest.raises(PermissionError):
        await WebGateway(screen).fetch("https://docs.example/to-data")
    before = len(requests)
    with pytest.raises(ValueError, match="redirects"):
        await WebGateway(screen).fetch("https://docs.example/loop")
    assert len(requests) - before == 4, "one request plus three hops, then stop"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["oversized", "gzip_bomb", "binary", "error_status", "advertised"])
async def test_gateway_bounds_and_filters_responses(monkeypatch, kind):
    def handler(request):
        if kind == "oversized":
            return httpx.Response(200, stream=Body(b"x" * 1_500_000), headers={"Content-Type": "text/plain"})
        if kind == "gzip_bomb":
            body = Body(gzip.compress(b"x" * 5_000_000))
            return httpx.Response(200, stream=body, headers={"Content-Type": "text/plain", "Content-Encoding": "gzip"})
        if kind == "binary":
            return page(b"\x00\x01", "application/octet-stream")
        if kind == "advertised":
            return httpx.Response(
                200, content=b"x", headers={"Content-Type": "text/plain", "Content-Length": "9000000"}
            )
        return page(b"missing", "text/plain", status=404)

    web(monkeypatch, handler)
    with pytest.raises(ValueError):
        await WebGateway(OutboundScreen()).fetch("https://docs.example/big")


@pytest.mark.asyncio
async def test_gateway_fetch_count_is_bounded(monkeypatch):
    web(monkeypatch, lambda request: page(b"ok", "text/plain"))
    gateway = WebGateway(OutboundScreen(), max_fetches=2)
    await gateway.fetch("https://docs.example/1")
    await gateway.fetch("https://docs.example/2")
    with pytest.raises(ValueError, match="budget"):
        await gateway.fetch("https://docs.example/3")


@pytest.mark.asyncio
async def test_search_is_offered_only_when_configured_and_queries_are_screened(monkeypatch):
    payload = {"results": [{"title": "Orders API", "url": "https://docs.example/orders", "content": "Pagination"}]}
    requests = web(monkeypatch, lambda request: httpx.Response(200, json=payload))
    screen = OutboundScreen(markers={"cust-0042"})
    assert [tool.name for tool in WebGateway(screen).tools()] == ["fetch"]
    monkeypatch.setattr(settings(), "research_search_url", "https://search.example/search?format=json&q={query}")
    monkeypatch.setattr(settings(), "research_search_header", "X-Key: search-key")
    gateway = WebGateway(screen)
    assert [tool.name for tool in gateway.tools()] == ["fetch", "search"]
    found = await gateway.search("acme erp orders api pagination")
    assert found["results"][0]["url"] == "https://docs.example/orders"
    assert requests[0].url.params["q"] == "acme erp orders api pagination"
    assert requests[0].headers["x-key"] == "search-key"
    with pytest.raises(PermissionError):
        await gateway.search("orders for CUST-0042")
    assert len(requests) == 1


def message(payload):
    return ResponseOutputMessage(
        type="message",
        role="assistant",
        id=uid(),
        status="completed",
        content=[ResponseOutputText(type="output_text", text=json.dumps(payload), annotations=[])],
    )


def tool_call(name, **arguments):
    return ResponseFunctionToolCall(
        type="function_call", name=name, arguments=json.dumps(arguments), call_id=uid(), id=uid()
    )


class Scripted(Model):
    def __init__(self, steps):
        self.steps, self.inputs, self.outputs, self.tool_names = list(steps), [], [], []

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        items = input if isinstance(input, list) else []
        self.tool_names = [tool.name for tool in tools]
        self.inputs.append(json.dumps(items, default=str) + (system_instructions or ""))
        self.outputs = [i["output"] for i in items if isinstance(i, dict) and i.get("type") == "function_call_output"]
        step = self.steps.pop(0)
        return ModelResponse(
            output=[step],
            usage=Usage(requests=1, input_tokens=20, output_tokens=10, total_tokens=30),
            response_id=uid(),
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


@pytest.mark.asyncio
async def test_research_step_sees_only_the_question(monkeypatch):
    requests = web(monkeypatch, lambda request: page(b"<p>Amounts are integers in cents.</p>"))
    researcher = Scripted(
        [tool_call("fetch", url="https://docs.example/amounts"), message({"notes": "Amounts are integer cents."})]
    )
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr("factory.research.Agent", lambda **kwargs: Agent(**{**kwargs, "model": researcher}))
    result = await research("What unit does the Acme API use for amounts?", OutboundScreen())
    assert result == {
        "question": "What unit does the Acme API use for amounts?",
        "notes": "Amounts are integer cents.",
        "sources": ["https://docs.example/amounts"],
    }
    assert len(requests) == 1
    with pytest.raises(ValueError):
        await research("x" * 500, OutboundScreen())
    with pytest.raises(PermissionError):
        await research("lookup CUST-0042", OutboundScreen(markers={"cust-0042"}))


async def parked_job(db, seeded, monkeypatch, builder_steps, researcher_steps, enabled=True, budget=None):
    _, _, agent, initial, suite, _ = seeded
    evaluation = await evaluate_suite(db, initial, suite, ("development", "regression"))
    job = new_job(db, agent, budget or Budget())
    job.state = "OPTIMIZING"
    job.checkpoint = {
        **job.checkpoint,
        "diagnosis": {"development_failures": development_evidence(db, evaluation)},
        "best_version_id": initial.id,
        "best_scorecard": evaluation.scorecard,
        "best_evaluation_id": evaluation.id,
    }
    db.commit()
    builder, researcher = Scripted(builder_steps), Scripted(researcher_steps)
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr(settings(), "research_enabled", enabled)
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": builder}))
    monkeypatch.setattr("factory.research.Agent", lambda **kwargs: Agent(**{**kwargs, "model": researcher}))
    return job, builder, researcher


@pytest.mark.asyncio
async def test_builder_research_is_isolated_accounted_and_recorded_as_provenance(db, seeded, monkeypatch):
    requests = web(monkeypatch, lambda request: page(b"<p>Customer aliases map nicknames to SKUs.</p>"))
    job, builder, researcher = await parked_job(
        db,
        seeded,
        monkeypatch,
        [
            # First the builder leaks a real case input into a question: it must be withheld.
            tool_call("research", question="How do I match 'Harbor Bistro: 2 kg chook' to a product?"),
            tool_call("research", question="How do ERP systems usually resolve customer product aliases?"),
            message({"hypothesis": "Resolve aliases as documented", "rules": {"resolve_aliases": True}}),
        ],
        [
            tool_call("fetch", url="https://docs.example/aliases"),
            message({"notes": "Aliases map nicknames to SKUs per customer."}),
        ],
    )
    await advance(db, job)
    db.commit()
    assert job.state == "RETESTING", (job.state, job.error)
    assert "research" in builder.tool_names
    assert json.loads(builder.outputs[0]) == {"error": WITHHELD}
    answered = json.loads(builder.outputs[1])
    assert answered["sources"] == ["https://docs.example/aliases"] and "Untrusted" in answered["warning"]
    # Exactly one page left the process, and nothing the researcher saw contains tenant data.
    assert [str(request.url) for request in requests] == ["https://docs.example/aliases"]
    seen_by_researcher = " ".join(researcher.inputs)
    for tenant_text in ("Harbor Bistro", "chook", "SKU-"):
        assert tenant_text not in seen_by_researcher
    assert "How do ERP systems usually resolve customer product aliases?" in seen_by_researcher
    # Researcher model calls are reserved and settled under their own role, inside the build budget.
    roles = [r.role for r in db.scalars(select(UsageRecord).where(UsageRecord.job_id == job.id))]
    assert sorted(roles) == ["optimizer", "optimizer", "optimizer", "researcher", "researcher"]
    assert all(r.status == "recorded" for r in db.scalars(select(UsageRecord).where(UsageRecord.job_id == job.id)))
    assert job.spent == pytest.approx(5 * 30 * settings().estimated_token_cost)
    event = db.scalar(
        select(ExecutionEvent).where(ExecutionEvent.job_id == job.id, ExecutionEvent.kind == "optimizer_investigation")
    )
    assert event.payload["withheld_outbound"] == ["question"]
    assert event.payload["research"] == [
        {
            "question": "How do ERP systems usually resolve customer product aliases?",
            "sources": ["https://docs.example/aliases"],
        }
    ]
    candidate = job.checkpoint["round"]["candidates"][0]
    assert candidate["research_sources"] == ["https://docs.example/aliases"]
    assert db.get(AgentVersion, candidate["version_id"]).spec["rules"]["resolve_aliases"] is True


@pytest.mark.asyncio
async def test_research_is_off_unless_enabled_and_capped_when_on(db, seeded, monkeypatch):
    requests = web(monkeypatch, lambda request: page(b"ok", "text/plain"))
    job, builder, _ = await parked_job(
        db, seeded, monkeypatch, [message({"hypothesis": "No change"})], [], enabled=False
    )
    await advance(db, job)
    db.commit()
    assert "research" not in builder.tool_names and requests == []


@pytest.mark.asyncio
async def test_research_calls_per_proposal_are_capped(db, seeded, monkeypatch):
    web(monkeypatch, lambda request: page(b"ok", "text/plain"))
    question = "How do ERP systems usually resolve customer product aliases?"
    job, builder, _ = await parked_job(
        db,
        seeded,
        monkeypatch,
        [
            tool_call("research", question=question),
            tool_call("research", question=question),
            tool_call("research", question=question),
            message({"hypothesis": "No change"}),
        ],
        [message({"notes": "first"}), message({"notes": "second"})],
    )
    await advance(db, job)
    db.commit()
    # An unchanged proposal is a rejected attempt; nothing is persisted or re-evaluated.
    assert job.state == "OPTIMIZING" and job.error is None, (job.state, job.error)
    assert job.checkpoint["attempts"][-1]["rejected_before_evaluation"] == "UnchangedProposal"
    assert "budget" in json.loads(builder.outputs[2])["error"].lower()
