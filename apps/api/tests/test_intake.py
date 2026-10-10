"""Build inputs: datasets become evaluation cases with the held-out part kept from the builder,
business context documents reach only the builder, and a build cannot start with nothing to judge it."""

import json
import socket

import httpx
import pytest
from agents import Agent, Model, ModelResponse, Usage
from fastapi.testclient import TestClient
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
from sqlalchemy import select

from factory.api import app, limits
from factory.config import settings
from factory.db import get_db, uid
from factory.evaluation import grade
from factory.intake import (
    CONTEXT_PAGE_CHARS,
    IntakeError,
    canonical,
    context_payload,
    derive_schemas,
    fetch_dataset,
    guess_mapping,
    parse_records,
    split_examples,
    to_examples,
    truth_source,
)
from factory.models import (
    AgentRecord,
    AgentVersion,
    AuditEvent,
    BuildIteration,
    BuildJob,
    ContextDocument,
    Dataset,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationSuite,
    ExecutionRun,
    Membership,
    Organization,
    User,
)
from factory.optimizer_tools import REFUSED, Investigation
from factory.schemas import AgentSpec, Budget
from factory.security import encrypt, passwords, token_for
from factory.workflow import TERMINAL, advance, new_job

PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
TOPICS = ("card", "loan", "transfer", "account")


def tickets(per_topic=30):
    """Rows whose correct answer is the first word, so a scripted agent can be right or wrong on purpose."""
    return [{"text": f"{topic} question number {n}", "category": topic} for n in range(per_topic) for topic in TOPICS]


def as_csv(rows):
    columns = list(rows[0])
    return "\n".join([",".join(columns), *(",".join(str(row[c]) for c in columns) for row in rows)])


@pytest.fixture
def client(db, seeded):
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    org, user, *_ = seeded
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
        yield client
    app.dependency_overrides.clear()


def member(db, org, role):
    user = User(email=f"{role}-{uid()[:8]}@example.invalid", password_hash=passwords.hash("test-password"))
    db.add(user)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role=role))
    db.commit()
    return {"Authorization": "Bearer " + token_for(user.id, org.id)}


def direct_agent(client, seeded, **extra):
    """A custom agent with no connection, as the create form makes one."""
    _, _, agent, *_ = seeded
    body = {"project_id": agent.project_id, "request": "Route each support ticket to the right queue", **extra}
    response = client.post("/agents", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_parsing_reads_csv_tsv_json_and_json_lines_alike():
    rows = [{"text": "card lost", "category": "card"}, {"text": "loan rate", "category": "loan"}]
    assert parse_records(as_csv(rows)) == rows
    assert parse_records("text\tcategory\ncard lost\tcard\nloan rate\tloan") == rows
    assert parse_records(json.dumps(rows)) == rows
    assert parse_records("\n".join(json.dumps(row) for row in rows)) == rows
    assert parse_records(json.dumps({"rows": [{"row_idx": 0, "row": row} for row in rows]})) == rows
    assert parse_records('﻿text,category\n"card, lost",card\n') == [{"text": "card, lost", "category": "card"}]


@pytest.mark.parametrize(
    "text,format",
    [
        ("", None),
        ("text,category\n", None),
        ("text,text\na,b\n", None),
        ("text,category\nonly-one-value\n", None),
        ('{"not": "a list"}', None),
        ('[{"text": {"nested": true}, "category": "card"}]', None),
        ("[1, 2, 3]", None),
        ("text,category\na,b\n", "parquet"),
        ("text,category\n" + "x" * 30_000 + ",card\n", None),
    ],
)
def test_parsing_refuses_what_it_cannot_read_instead_of_guessing(text, format):
    with pytest.raises(IntakeError):
        parse_records(text, format)


def test_mapping_is_guessed_only_when_the_answer_column_is_clear():
    assert guess_mapping(tickets(2)) == {"input": {"text": "text"}, "expected": {"category": "category"}}
    # An identifier column is neither request nor answer.
    with_id = [{"id": n, **row} for n, row in enumerate(tickets(2))]
    assert guess_mapping(with_id) == {"input": {"text": "text"}, "expected": {"category": "category"}}
    # No telling name, but one of two columns repeats: that one is the answer.
    renamed = [{"utterance": row["text"], "queue": row["category"]} for row in tickets(5)]
    assert guess_mapping(renamed) == {"input": {"text": "utterance"}, "expected": {"queue": "queue"}}
    # Several inputs keep their own names.
    wide = [{"subject": "s", "body": "b", "label": "x"}]
    assert guess_mapping(wide)["input"] == {"subject": "subject", "body": "body"}
    with pytest.raises(IntakeError):
        guess_mapping([{"a": n, "b": n, "c": n} for n in range(6)])


def test_unusable_and_contradictory_rows_are_left_out_and_counted():
    rows = [
        {"text": "card lost", "category": "card"},
        {"text": "card lost", "category": "card"},
        {"text": "which queue", "category": "loan"},
        {"text": "which queue", "category": "card"},
        {"text": "no answer", "category": ""},
        {"text": " ", "category": "card"},
    ]
    examples, dropped = to_examples(rows, guess_mapping(rows))
    assert examples == [({"text": "card lost"}, {"category": "card"})]
    assert dropped == {"missing_answer": 1, "empty_input": 1, "duplicate_input": 1, "contradictory_answer": 2}


def test_split_is_exact_deterministic_balanced_and_never_shares_an_input():
    examples, _ = to_examples(tickets(), guess_mapping(tickets()))
    sizes = {"development": 40, "selection": 16, "regression": 8, "validation": 24}
    first = split_examples(examples, sizes, "seed")
    assert {split: len(rows) for split, rows in first.items()} == sizes
    assert first == split_examples(list(reversed(examples)), sizes, "seed"), "order of the file does not matter"
    assert first != split_examples(examples, sizes, "another seed")
    inputs = [canonical(item[0]) for rows in first.values() for item in rows]
    assert len(inputs) == len(set(inputs))
    for rows in first.values():
        counts = {topic: sum(item[1]["category"] == topic for item in rows) for topic in TOPICS}
        assert max(counts.values()) - min(counts.values()) <= 2, counts
    # Too little data keeps the proportions and still holds some back.
    small = split_examples(examples[:10], {"development": 60, "regression": 0, "validation": 60}, "seed")
    assert {split: len(rows) for split, rows in small.items()} == {
        "development": 5,
        "selection": 0,
        "regression": 0,
        "validation": 5,
    }
    with pytest.raises(IntakeError):
        split_examples(examples[:1], sizes, "seed")
    with pytest.raises(IntakeError):
        split_examples(examples, {"development": 10, "validation": 0}, "seed")


def test_schemas_are_read_off_the_data_and_a_repeating_answer_becomes_a_vocabulary():
    examples, _ = to_examples(tickets(), guess_mapping(tickets()))
    input_schema, output_schema, labels = derive_schemas(examples)
    assert input_schema == {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }
    assert output_schema["required"] == ["category"]
    assert output_schema["properties"]["category"] == {"type": "string", "enum": sorted(TOPICS)}
    assert labels == {"category": sorted(TOPICS)}
    # Free text and numbers are not a vocabulary.
    free = [({"text": str(n)}, {"summary": f"unique {n}", "amount": n}) for n in range(10)]
    _, schema, labels = derive_schemas(free)
    assert schema["properties"] == {"summary": {"type": "string"}, "amount": {"type": "integer"}} and labels == {}


def test_a_build_cannot_start_with_nothing_to_judge_it(client, seeded, db, monkeypatch):
    created = direct_agent(client, seeded)
    assert created["template"] == "custom" and created["version"]["spec"]["tools"] == []
    assert created["version"]["spec"]["instructions"].endswith("Task: Route each support ticket to the right queue")
    assert client.get(f"/agents/{created['id']}").json()["truth_source"] is None
    refused = client.post(f"/agents/{created['id']}/builds", json={})
    assert refused.status_code == 422 and "judged against" in refused.json()["error"]["message"]
    assert db.scalar(select(BuildJob).where(BuildJob.agent_id == created["id"])) is None
    # The same rule holds below the API.
    with pytest.raises(ValueError):
        new_job(db, db.get(AgentRecord, created["id"]), Budget())

    # A stated reason is recorded and lets the build draft cases for a person to accept.
    assert (
        client.post(
            "/agents", json={"project_id": created["project_id"], "request": "x" * 20, "no_data_reason": "short"}
        ).status_code
        == 422
    )
    stated = direct_agent(
        client, seeded, no_data_reason="Totals follow from the listed prices, so answers are checkable by rule."
    )
    assert client.get(f"/agents/{stated['id']}").json()["truth_source"] == "rules"
    # In demo mode an agent without tools has nothing to run on, and the build says so instead of failing every case.
    demo = client.post(f"/agents/{stated['id']}/builds", json={})
    assert demo.status_code == 422 and "live model" in demo.json()["error"]["message"]
    monkeypatch.setattr(settings(), "execution_mode", "live")
    assert client.post(f"/agents/{stated['id']}/builds", json={}).status_code == 201
    event = db.scalar(
        select(AuditEvent).where(AuditEvent.resource_id == stated["id"], AuditEvent.action == "agent_created")
    )
    assert event.detail == {"no_data_stated": True}

    # Fixture-backed templates already have cases on both sides.
    assert truth_source(db, seeded[2]) == "cases"


def test_attaching_a_dataset_creates_split_cases_and_pins_the_agent_shape(client, seeded, db, monkeypatch):
    created = direct_agent(client, seeded)
    response = client.post(
        f"/agents/{created['id']}/datasets",
        json={"name": "Support tickets", "content": as_csv(tickets()), "development": 40, "validation": 20},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["rows"] == 120 and body["origin"] == "upload"
    assert body["mapping"] == {"input": {"text": "text"}, "expected": {"category": "category"}}
    # Unless told otherwise, as many rows are set aside for scoring changes as the builder may read.
    assert body["profile"]["splits"] == {"development": 40, "selection": 40, "regression": 0, "validation": 20}
    assert body["profile"]["answers"] == {"category": sorted(TOPICS)}

    cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == created["suite_id"])))
    assert len(cases) == 100 and {case.source for case in cases} == {"dataset"}
    assert all(case.org_id == created["org_id"] for case in cases)
    for case in cases:
        assert case.assertions == [
            {
                "op": "equals",
                "path": "category",
                "value": case.input["text"].split()[0],
                "category": "structured_accuracy",
            }
        ]
    # The profile is shown to the builder, so its examples come from the development split only.
    development = {canonical(case.input) for case in cases if case.split == "development"}
    assert body["profile"]["examples"] and all(
        canonical(item["input"]) in development for item in body["profile"]["examples"]
    )

    spec = body["version"]["spec"]
    assert spec["input_schema"]["required"] == ["text"] and spec["output_schema"]["properties"]["category"][
        "enum"
    ] == sorted(TOPICS)
    assert body["version"]["number"] == 2 and "Support tickets" in body["version"]["hypothesis"]
    detail = client.get(f"/agents/{created['id']}").json()
    assert detail["truth_source"] == "cases" and detail["best_version_id"] is None
    assert client.get(f"/agents/{created['id']}/datasets").json()["total"] == 1
    monkeypatch.setattr(settings(), "execution_mode", "live")
    assert client.post(f"/agents/{created['id']}/builds", json={}).status_code == 201
    # Data cannot move under a running build.
    again = client.post(f"/agents/{created['id']}/datasets", json={"name": "More", "content": as_csv(tickets(40))})
    assert again.status_code == 409


def test_a_second_dataset_never_brings_a_held_out_row_back_in_another_split(client, seeded, db):
    created = direct_agent(client, seeded)
    url = f"/agents/{created['id']}/datasets"
    assert (
        client.post(
            url,
            json={"name": "First", "content": as_csv(tickets(10)), "development": 20, "selection": 0, "validation": 20},
        ).status_code
        == 201
    )
    before = {
        canonical(case.input): case.split
        for case in db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == created["suite_id"]))
    }
    # The same rows again: nothing is left to import.
    same = client.post(url, json={"name": "Again", "content": as_csv(tickets(10))})
    assert same.status_code == 422 and "already imported" in same.json()["error"]["message"]
    # A larger file that contains the old rows adds only the new ones.
    more = client.post(
        url,
        json={"name": "Second", "content": as_csv(tickets(20)), "development": 10, "selection": 0, "validation": 10},
    )
    assert more.status_code == 201 and more.json()["profile"]["dropped"]["already_in_suite"] == 40
    after = {}
    for case in db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == created["suite_id"])):
        assert canonical(case.input) not in after, "an input appears twice"
        after[canonical(case.input)] = case.split
    assert len(after) == 60 and all(after[key] == split for key, split in before.items())
    # Different fields would make the earlier cases ungradable.
    other = [{"text": f"t{n}", "priority": "high" if n % 2 else "low"} for n in range(40)]
    mismatch = client.post(url, json={"name": "Third", "content": json.dumps(other)})
    assert mismatch.status_code == 422 and "different fields" in mismatch.json()["error"]["message"]


def test_an_explicit_mapping_overrides_the_guess_and_is_checked(client, seeded):
    created = direct_agent(client, seeded)
    rows = [
        {"subject": f"s{n}", "body": f"{TOPICS[n % 4]} body {n}", "queue": TOPICS[n % 4], "agent": "sam"}
        for n in range(40)
    ]
    url = f"/agents/{created['id']}/datasets"
    for mapping in (
        {"input": {"body": "missing"}, "expected": {"queue": "queue"}},
        {"input": {"body": "body"}, "expected": {"queue": "body"}},
        {"input": {"not a name": "body"}, "expected": {"queue": "queue"}},
    ):
        assert client.post(url, json={"name": "T", "content": json.dumps(rows), "mapping": mapping}).status_code == 422
    assert (
        client.post(
            url, json={"name": "T", "content": json.dumps(rows), "url": "https://data.example/x.csv"}
        ).status_code
        == 422
    )
    mapping = {"input": {"message": "body"}, "expected": {"queue": "queue"}}
    made = client.post(
        url, json={"name": "T", "content": json.dumps(rows), "mapping": mapping, "development": 8, "validation": 8}
    )
    assert made.status_code == 201
    assert made.json()["version"]["spec"]["input_schema"]["properties"] == {"message": {"type": "string"}}


def test_datasets_and_documents_are_tenant_scoped_and_need_write_access(client, seeded, db):
    org, *_ = seeded
    created = direct_agent(client, seeded)
    document = client.post(
        f"/agents/{created['id']}/context", json={"name": "Routing guide", "text": "Card issues go to the card queue."}
    ).json()
    viewer = member(db, org, "viewer")
    assert (
        client.post(
            f"/agents/{created['id']}/datasets", headers=viewer, json={"name": "T", "content": as_csv(tickets())}
        ).status_code
        == 403
    )
    assert (
        client.post(f"/agents/{created['id']}/context", headers=viewer, json={"name": "n", "text": "t"}).status_code
        == 403
    )
    assert client.delete(f"/context/{document['id']}", headers=viewer).status_code == 403
    assert client.get(f"/agents/{created['id']}/context", headers=viewer).status_code == 200

    other = Organization(name="Other tenant")
    db.add(other)
    db.flush()
    outsider = member(db, other, "admin")
    for method, path, body in (
        ("post", f"/agents/{created['id']}/datasets", {"name": "T", "content": as_csv(tickets())}),
        ("get", f"/agents/{created['id']}/datasets", None),
        ("post", f"/agents/{created['id']}/context", {"name": "n", "text": "t"}),
        ("get", f"/agents/{created['id']}/context", None),
        ("get", f"/context/{document['id']}", None),
        ("delete", f"/context/{document['id']}", None),
    ):
        response = client.request(method, path, headers=outsider, json=body)
        assert response.status_code == 404, (method, path)
    assert db.scalar(select(Dataset)) is None and db.get(ContextDocument, document["id"]) is not None


def test_context_documents_are_bounded_named_once_and_stripped_of_credentials(client, seeded, db):
    *_, connection = seeded
    connection.encrypted_secret = encrypt("tenant-credential-9f3a71c2")
    db.commit()
    created = direct_agent(client, seeded)
    url = f"/agents/{created['id']}/context"
    text = "Refunds over 500 need a manager. The ERP password is tenant-credential-9f3a71c2. " + "Procedure. " * 200
    made = client.post(url, json={"name": "Refund policy", "text": text})
    assert made.status_code == 201 and "text" not in made.json() and len(made.json()["excerpt"]) <= 600
    stored = db.get(ContextDocument, made.json()["id"])
    assert "tenant-credential-9f3a71c2" not in stored.text and "Refunds over 500" in stored.text
    assert "tenant-credential-9f3a71c2" not in client.get(f"/context/{stored.id}").text
    assert client.post(url, json={"name": "Refund policy", "text": "again"}).status_code == 422
    assert client.post(url, json={"name": "Binary", "text": "a\x00b"}).status_code == 422
    assert client.post(url, json={"name": "Huge", "text": "x" * 200_001}).status_code == 422
    listed = client.get(url).json()
    assert listed["total"] == 1 and listed["items"][0]["chars"] == stored.chars
    assert client.delete(f"/context/{stored.id}").status_code == 204
    assert client.get(url).json()["total"] == 0
    for n in range(20):
        assert client.post(url, json={"name": f"Document {n}", "text": "short"}).status_code == 201
    assert client.post(url, json={"name": "One too many", "text": "short"}).status_code == 422


def test_context_sent_in_one_request_is_bounded_and_says_when_it_is_cut(db, seeded):
    _, _, agent, *_ = seeded
    assert context_payload(db, agent) == []
    db.add_all(
        [
            ContextDocument(
                org_id=agent.org_id, agent_id=agent.id, name="Short", text="Brief note.", chars=11, content_hash="a"
            ),
            ContextDocument(
                org_id=agent.org_id, agent_id=agent.id, name="Long", text="y" * 90_000, chars=90_000, content_hash="b"
            ),
        ]
    )
    db.flush()
    payload = {item["name"]: item for item in context_payload(db, agent, budget=10_000)}
    assert payload["Short"] == {"name": "Short", "characters": 11, "text": "Brief note.", "truncated": False}
    assert (
        payload["Long"]["truncated"]
        and len(payload["Long"]["text"]) == 5_000
        and payload["Long"]["characters"] == 90_000
    )


async def call(tools, tool_name, **arguments):
    tool = next(t for t in tools if t.name == tool_name)
    return json.loads(await tool.on_invoke_tool(None, json.dumps(arguments)))


@pytest.mark.asyncio
async def test_the_investigator_reads_only_this_agents_documents_a_page_at_a_time(db, seeded):
    org, _, agent, initial, *_ = seeded
    job = new_job(db, agent, Budget())
    spec = AgentSpec.model_validate(initial.spec)
    assert "read_context" not in {tool.name for tool in Investigation(db, job, spec, None, []).tools()}

    other_org = Organization(name="Other tenant")
    sibling = AgentRecord(
        org_id=org.id, project_id=agent.project_id, name="Sibling", request="Another task here", template="custom"
    )
    db.add_all([other_org, sibling])
    db.flush()
    long_text = "Card disputes go to the card queue. " + "z" * (CONTEXT_PAGE_CHARS + 500)
    db.add_all(
        [
            ContextDocument(
                org_id=org.id,
                agent_id=agent.id,
                name="Routing guide",
                text=long_text,
                chars=len(long_text),
                content_hash="a",
            ),
            ContextDocument(
                org_id=org.id,
                agent_id=sibling.id,
                name="Sibling notes",
                text="Not for this build.",
                chars=19,
                content_hash="b",
            ),
            ContextDocument(
                org_id=other_org.id,
                agent_id=agent.id,
                name="Foreign",
                text="Another tenant's text.",
                chars=22,
                content_hash="c",
            ),
        ]
    )
    db.flush()
    investigation = Investigation(db, job, spec, None, [])
    tools = investigation.tools()
    assert (await call(tools, "list_context"))["documents"] == [{"name": "Routing guide", "characters": len(long_text)}]
    first = await call(tools, "read_context", name="Routing guide")
    assert first["text"].startswith("Card disputes") and first["next_offset"] == CONTEXT_PAGE_CHARS
    rest = await call(tools, "read_context", name="Routing guide", offset=first["next_offset"])
    assert first["text"] + rest["text"] == long_text and rest["next_offset"] is None
    for name in ("Sibling notes", "Foreign", "No such document"):
        assert await call(tools, "read_context", name=name) == {"error": REFUSED}
    assert len(investigation.denied) == 3


def web(monkeypatch, handler):
    """Owned test transport in place of the pinned client; records every outbound request."""
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: PUBLIC)
    monkeypatch.setattr(
        "factory.intake.pinned_client",
        lambda url, hosts, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(record), **kwargs),
    )
    return requests


def served(body, kind="text/csv", status=200, headers=None):
    return httpx.Response(status, content=body, headers={"Content-Type": kind, **(headers or {})})


@pytest.mark.asyncio
async def test_a_dataset_address_is_fetched_without_credentials_and_redirects_are_checked_again(monkeypatch):
    def handler(request):
        if request.url.host == "data.example":
            return served(b"", status=302, headers={"Location": "https://cdn.example/files/tickets.csv"})
        return served(as_csv(tickets(1)).encode())

    requests = web(monkeypatch, handler)
    assert parse_records(await fetch_dataset("https://data.example/tickets.csv#part")) == tickets(1)
    assert [str(request.url) for request in requests] == [
        "https://data.example/tickets.csv",
        "https://cdn.example/files/tickets.csv",
    ]
    assert all("authorization" not in request.headers and "cookie" not in request.headers for request in requests)

    # A redirect to somewhere a dataset may not come from is refused when it is followed, not trusted.
    requests = web(
        monkeypatch, lambda request: served(b"", status=302, headers={"Location": "http://data.example/plain"})
    )
    with pytest.raises(IntakeError):
        await fetch_dataset("https://data.example/tickets.csv")
    assert len(requests) == 1
    web(monkeypatch, lambda request: served(b"", status=302, headers={"Location": str(request.url) + "x"}))
    with pytest.raises(IntakeError, match="too many"):
        await fetch_dataset("https://data.example/loop")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://data.example/tickets.csv",
        "https://user:secret@data.example/tickets.csv",
        "https://data.example:8443/tickets.csv",
        "file:///etc/passwd",
        "https:///tickets.csv",
    ],
)
async def test_unsafe_dataset_addresses_are_refused_before_any_request(monkeypatch, url):
    requests = web(monkeypatch, lambda request: served(b"never"))
    with pytest.raises(IntakeError):
        await fetch_dataset(url)
    assert requests == []


@pytest.mark.asyncio
async def test_fetched_datasets_are_bounded_and_must_be_text(monkeypatch):
    web(monkeypatch, lambda request: served(b"x" * 5_000_001))
    with pytest.raises(IntakeError, match="larger"):
        await fetch_dataset("https://data.example/huge.csv")
    web(monkeypatch, lambda request: served(b"\x89PNG", kind="image/png"))
    with pytest.raises(IntakeError):
        await fetch_dataset("https://data.example/picture")
    web(monkeypatch, lambda request: served(b"\xff\xfe\x00binary", kind="application/octet-stream"))
    with pytest.raises(IntakeError, match="UTF-8"):
        await fetch_dataset("https://data.example/blob")
    web(monkeypatch, lambda request: served(b"gone", status=404))
    with pytest.raises(IntakeError, match="404"):
        await fetch_dataset("https://data.example/missing.csv")


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.8", "169.254.169.254", "::1"])
async def test_dataset_fetches_use_the_pinned_transport_which_refuses_private_addresses(monkeypatch, address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(family, socket.SOCK_STREAM, 6, "", (address, 443))])
    connected = []
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: connected.append(a))
    with pytest.raises(Exception) as caught:
        await fetch_dataset("https://internal.example/tickets.csv")
    assert not isinstance(caught.value, AssertionError) and connected == []


def test_a_dataset_can_be_attached_from_an_address(client, seeded, monkeypatch, db):
    requests = web(monkeypatch, lambda request: served(as_csv(tickets()).encode(), kind="text/plain"))
    created = direct_agent(client, seeded)
    made = client.post(
        f"/agents/{created['id']}/datasets",
        json={"name": "Public tickets", "url": "https://data.example/tickets.csv", "development": 12, "validation": 12},
    )
    assert made.status_code == 201, made.text
    assert made.json()["origin"] == "url" and made.json()["source_url"] == "https://data.example/tickets.csv"
    assert len(requests) == 1
    unreachable = client.post(
        f"/agents/{created['id']}/datasets", json={"name": "Bad", "url": "http://data.example/tickets.csv"}
    )
    assert unreachable.status_code == 422 and "https" in unreachable.json()["error"]["message"]


def message(payload):
    return ResponseOutputMessage(
        type="message",
        role="assistant",
        id=uid(),
        status="completed",
        content=[ResponseOutputText(type="output_text", text=json.dumps(payload), annotations=[])],
    )


def reply(payload):
    return ModelResponse(
        output=[message(payload)],
        usage=Usage(requests=1, input_tokens=5, output_tokens=5, total_tokens=10),
        response_id=uid(),
    )


def user_text(items):
    if isinstance(items, str):
        return items
    return next(i["content"] for i in items if isinstance(i, dict) and i.get("role") == "user")


class TicketAgent(Model):
    """The deployed agent's provider. It routes by the first word only once its instructions say to."""

    def __init__(self):
        self.seen = []

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        payload = json.loads(user_text(input))
        # A repair pass wraps the input and adds what the verifiers objected to.
        text = payload.get("input", payload)["text"]
        self.seen.append({"instructions": system_instructions, "tools": [tool.name for tool in tools], "text": text})
        return reply({"category": text.split()[0] if "first word" in system_instructions else "card"})

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


class Builder(Model):
    """The factory roles' provider: an architect that restates the baseline and an optimizer with one idea."""

    def __init__(self):
        self.requests = []

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        payload = json.loads(user_text(input))
        self.requests.append(
            {
                "role": "architect" if "baseline" in payload else "optimizer",
                "payload": payload,
                "tools": [tool.name for tool in tools],
            }
        )
        if "baseline" in payload:
            # An architect that tries to move the fields the cases are graded on.
            return reply(
                {
                    **payload["baseline"],
                    "name": "Ticket Router",
                    "instructions": "Route the ticket to a queue.",
                    "output_schema": {"type": "object"},
                }
            )
        return reply(
            {
                "hypothesis": "Wrong queues come from ignoring the topic; route by the first word",
                "instructions": "Route the ticket to the queue named by its first word.",
            }
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


@pytest.mark.asyncio
async def test_a_tool_less_agent_is_built_from_data_and_judged_on_rows_the_builder_never_saw(
    client, seeded, db, monkeypatch
):
    created = direct_agent(client, seeded)
    client.post(
        f"/agents/{created['id']}/context",
        json={"name": "Routing guide", "text": "Each ticket belongs to the queue of its topic."},
    )
    attached = client.post(
        f"/agents/{created['id']}/datasets",
        json={"name": "Support tickets", "content": as_csv(tickets()), "development": 12, "validation": 12},
    )
    assert attached.status_code == 201

    builder, ticket_agent = Builder(), TicketAgent()
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": builder}))
    from factory.runtime import reconstruct_agent

    def bind(context, mode):
        built = reconstruct_agent(context, mode)
        built.model = ticket_agent
        return built

    monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)

    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    for _ in range(200):
        if job.state in TERMINAL:
            break
        await advance(db, job)
        db.commit()
    assert job.state == "READY_FOR_REVIEW", (job.state, job.error, job.checkpoint.get("stop_reason"))

    # No tools were offered or needed, and the absence of tool calls is not held against the agent.
    assert all(call["tools"] == [] for call in ticket_agent.seen)
    result = db.scalar(select(EvaluationResult))
    assert "tool_correctness" not in {check["category"] for check in result.checks}
    assert db.get(ExecutionRun, result.execution_id).metrics["tools_offered"] == 0

    # The architect could not move the graded fields, and the data fixed the vocabulary.
    versions = list(
        db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.number))
    )
    designed = versions[2].spec
    assert designed["name"] == "Ticket Router" and designed["output_schema"]["properties"]["category"][
        "enum"
    ] == sorted(TOPICS)
    assert designed["input_schema"] == attached.json()["version"]["spec"]["input_schema"]
    assert agent.best_version_id == versions[-1].id and "first word" in versions[-1].spec["instructions"]

    # First version half right on development, final version right on the held-out rows.
    card = job.checkpoint["validation_scorecard"]
    assert card["total"] == 12 and card["score"] == 1 and set(card["splits"]) == {"validation"}

    cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == created["suite_id"])))
    # Neither the rows held back for the final judgement nor the rows each change is scored on.
    held_out = [case.input["text"] for case in cases if case.split in ("validation", "selection")]
    assert sum(case.split == "selection" for case in cases) == 12
    development = [case.input["text"] for case in cases if case.split == "development"]
    everything_sent = json.dumps([request["payload"] for request in builder.requests])
    # Whole values, with their closing quote: one ticket's text is a prefix of another's.
    assert any(json.dumps(text) in everything_sent for text in development), "the builder works from development rows"
    assert not any(json.dumps(text) in everything_sent for text in held_out), "a held-out row reached the builder"
    # Both roles were given the customer's document; the deployed agent was not.
    roles = {request["role"]: request["payload"] for request in builder.requests}
    assert roles["architect"]["business_context"][0]["text"] == "Each ticket belongs to the queue of its topic."
    assert roles["architect"]["data"][0]["answers"] == {"category": sorted(TOPICS)}
    assert roles["optimizer"]["business_context"][0]["name"] == "Routing guide"
    assert not any("belongs to the queue of its topic" in call["instructions"] for call in ticket_agent.seen)
    # A suite drawn from data has no regression cases yet; held-out evidence is what approval needs.
    approved = client.post(f"/versions/{agent.best_version_id}/approve")
    assert approved.status_code == 200 and approved.json()["quality_gate"]["cases"] == 36
    unmeasured = client.post(f"/versions/{versions[0].id}/approve")
    assert unmeasured.status_code == 409


@pytest.mark.asyncio
async def test_a_build_that_runs_out_of_rounds_still_reports_its_held_out_score(client, seeded, db, monkeypatch):
    created = direct_agent(client, seeded)
    client.post(
        f"/agents/{created['id']}/datasets",
        json={"name": "Support tickets", "content": as_csv(tickets()), "development": 12, "validation": 8},
    )

    class Stuck(Builder):
        """An optimizer whose ideas never help."""

        async def get_response(self, system_instructions, input, *args, **kwargs):
            payload = json.loads(user_text(input))
            if "baseline" in payload:
                return await super().get_response(system_instructions, input, *args, **kwargs)
            self.requests.append({"role": "optimizer", "payload": payload, "tools": []})
            return reply(
                {
                    "hypothesis": f"Idea {len(self.requests)}",
                    "instructions": f"Try harder, attempt {len(self.requests)}.",
                }
            )

    builder, ticket_agent = Stuck(), TicketAgent()
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": builder}))
    from factory.runtime import reconstruct_agent

    def bind(context, mode):
        built = reconstruct_agent(context, mode)
        built.model = ticket_agent
        return built

    monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, stagnation_limit=2, investigator_turns=0))
    db.commit()
    for _ in range(300):
        if job.state in TERMINAL:
            break
        await advance(db, job)
        db.commit()
    # Exhausted, not ready: the target was never met. But the best version was measured on held-out rows.
    assert job.state == "BUDGET_EXHAUSTED" and job.checkpoint["stop_reason"] == "iterations_or_stagnation_limit"
    card = job.checkpoint["validation_scorecard"]
    assert card["total"] == 8 and set(card["splits"]) == {"validation"} and card["score"] == 0.25
    assert job.checkpoint["version_id"] == agent.best_version_id
    held_out = db.get(EvaluationRun, job.checkpoint["evaluation_id"])
    assert held_out.version_id == agent.best_version_id and held_out.status == "completed"
    # The measurement is not a pass: this version is far below the quality policy.
    assert client.post(f"/versions/{agent.best_version_id}/approve").status_code == 409


def test_a_tool_less_agent_cannot_run_in_demo_mode_and_says_so(client, seeded, db):
    created = direct_agent(client, seeded)
    client.post(
        f"/agents/{created['id']}/datasets",
        json={"name": "T", "content": as_csv(tickets()), "development": 4, "validation": 4},
    )
    agent = db.get(AgentRecord, created["id"])
    version = db.scalar(
        select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.number.desc())
    )
    suite = db.scalar(select(EvaluationSuite).where(EvaluationSuite.agent_id == agent.id))
    import asyncio

    from factory.evaluation import evaluate_suite

    evaluation = asyncio.run(evaluate_suite(db, version, suite, ("development",)))
    assert evaluation.scorecard["score"] == 0
    run = db.scalar(select(ExecutionRun).where(ExecutionRun.version_id == version.id))
    assert run.status == "failed" and run.error == "ValueError"


def test_tool_use_is_still_required_of_an_agent_that_has_tools():
    from types import SimpleNamespace

    case = SimpleNamespace(assertions=[], input={})
    for offered, expected in ((None, True), (2, True), (0, False)):
        metrics = {"tool_calls": 0, **({} if offered is None else {"tools_offered": offered})}
        run = SimpleNamespace(output={}, status="completed", metrics=metrics, error=None)
        checks, _ = grade(run, case)
        assert ("tool_correctness" in {check["category"] for check in checks}) is expected


@pytest.mark.asyncio
async def test_a_check_that_rejects_known_correct_answers_is_removed_before_anything_is_scored(
    client, seeded, db, monkeypatch
):
    created = direct_agent(client, seeded)
    client.post(
        f"/agents/{created['id']}/datasets",
        json={"name": "Support tickets", "content": as_csv(tickets()), "development": 12, "validation": 8},
    )

    class Overcautious(Builder):
        """An architect that adds one sound check and one that no correct answer can pass."""

        async def get_response(self, system_instructions, input, *args, **kwargs):
            payload = json.loads(user_text(input))
            if "baseline" not in payload:
                return await super().get_response(system_instructions, input, *args, **kwargs)
            self.requests.append({"role": "architect", "payload": payload, "tools": []})
            return reply(
                {
                    **payload["baseline"],
                    "instructions": "Route the ticket to the queue named by its first word.",
                    "verifiers": [
                        {"id": "known_queue", "kind": "one_of", "path": "category", "values": list(TOPICS)},
                        # Rejects every known answer: caught by reading the answers, before anything runs.
                        {"id": "wrong_vocabulary", "kind": "one_of", "path": "category", "values": ["billing"]},
                        # About a field the answers do not mention: only running it can show it is wrong.
                        {"id": "needs_confidence", "kind": "required", "path": "confidence"},
                    ],
                }
            )

    builder, ticket_agent = Overcautious(), TicketAgent()
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": builder}))
    from factory.runtime import reconstruct_agent

    def bind(context, mode):
        built = reconstruct_agent(context, mode)
        built.model = ticket_agent
        return built

    monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, investigator_turns=0))
    db.commit()
    for _ in range(300):
        if job.state in TERMINAL:
            break
        await advance(db, job)
        db.commit()
    assert job.state == "READY_FOR_REVIEW", (job.state, job.error, job.checkpoint.get("stop_reason"))
    best = db.get(AgentVersion, agent.best_version_id)
    # The sound check stays. One bad check was removed before any scoring, the other after one pass.
    assert [verifier["id"] for verifier in best.spec["verifiers"]] == ["known_queue"]
    versions = list(
        db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.number))
    )
    assert versions[2].hypothesis.endswith("[removed checks that reject known-correct answers: wrong_vocabulary]")
    assert [verifier["id"] for verifier in versions[2].spec["verifiers"]] == ["known_queue", "needs_confidence"]
    assert best.hypothesis == "Removed checks that rejected correct answers: needs_confidence"
    # The broken version was never scored as a round, so the first recorded score is a real one.
    assert job.iteration == 1 and job.checkpoint["best_scorecard"]["score"] == 1
    assert not [request for request in builder.requests if request["role"] == "optimizer"]
    assert job.checkpoint["validation_scorecard"]["score"] == 1


def test_usage_is_priced_per_model_on_input_and_output_and_flat_otherwise(monkeypatch):
    from types import SimpleNamespace

    from factory.pricing import model_name, prices, reservation, usage_cost

    usage = SimpleNamespace(input_tokens=1000, output_tokens=200, total_tokens=1200)
    monkeypatch.setattr(settings(), "model_prices", {"big-model": [5.0, 30.0]})
    assert usage_cost(usage, "big-model") == pytest.approx(1000 * 5e-6 + 200 * 30e-6)
    # A dated snapshot is the same model; a different model that merely shares a prefix is not.
    assert prices("big-model-2026-04-23") == prices("big-model")
    assert prices("big-model-pro") is None
    flat = 1200 * settings().estimated_token_cost
    assert usage_cost(usage, "big-model-pro") == usage_cost(usage, None) == pytest.approx(flat)
    assert reservation("big-model", 1000, 200) == pytest.approx(1000 * 5e-6 + 200 * 30e-6)
    # Only a call that really went to a named provider model is priced by name.
    assert model_name(SimpleNamespace(model="big-model")) == "big-model"
    assert model_name(SimpleNamespace(model=object())) is None


def test_replies_are_not_capped_unless_configured(db, seeded, monkeypatch):
    from factory.builder import reply_limit

    assert settings().output_token_limit == 0 and reply_limit() is None
    monkeypatch.setattr(settings(), "output_token_limit", 9000)
    assert reply_limit() == 9000


class Memoriser(Model):
    """A deployed agent that is right only about messages its instructions quote."""

    async def get_response(self, system_instructions, input, *args, **kwargs):
        payload = json.loads(user_text(input))
        text = payload.get("input", payload)["text"]
        return reply({"category": text.split()[0] if json.dumps(text) in system_instructions else "card"})

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


class Crammer(Builder):
    """An optimizer that writes the failures it was shown into the instructions, answers and all."""

    async def get_response(self, system_instructions, input, *args, **kwargs):
        payload = json.loads(user_text(input))
        if "baseline" in payload:
            return await super().get_response(system_instructions, input, *args, **kwargs)
        self.requests.append({"role": "optimizer", "payload": payload, "tools": []})
        seen = [failure["input"]["text"] for failure in payload["development_failures"]]
        return reply(
            {
                "hypothesis": f"Memorise the {len(seen)} failing messages, attempt {len(self.requests)}",
                "instructions": f"Attempt {len(self.requests)}. Known messages: "
                + " ".join(json.dumps(t) for t in seen),
            }
        )


@pytest.mark.asyncio
async def test_a_change_that_only_fits_the_rows_the_builder_read_is_not_kept(client, seeded, db, monkeypatch):
    created = direct_agent(client, seeded)
    client.post(
        f"/agents/{created['id']}/datasets",
        json={"name": "Support tickets", "content": as_csv(tickets()), "development": 12, "validation": 8},
    )
    builder = Crammer()
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    monkeypatch.setattr("factory.builder.Agent", lambda **kwargs: Agent(**{**kwargs, "model": builder}))
    from factory.runtime import reconstruct_agent

    def bind(context, mode):
        built = reconstruct_agent(context, mode)
        built.model = Memoriser()
        return built

    monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)
    agent = db.get(AgentRecord, created["id"])
    job = new_job(db, agent, Budget(target_score=1, stagnation_limit=2, investigator_turns=0))
    db.commit()
    for _ in range(400):
        if job.state in TERMINAL:
            break
        await advance(db, job)
        db.commit()
    assert job.state == "BUDGET_EXHAUSTED"
    rounds = list(
        db.scalars(select(BuildIteration).where(BuildIteration.job_id == job.id).order_by(BuildIteration.number))
    )
    assert [row.promoted for row in rounds] == [True, False, False]
    # The crammed version is perfect on the rows it memorised and no better on the rows it never saw.
    first, crammed = rounds[0].scorecard["splits"], rounds[1].scorecard["splits"]
    assert first["development"]["score"] == 0.25 and crammed["development"]["score"] == 1
    assert first["selection"]["score"] == crammed["selection"]["score"] == 0.25
    assert agent.best_version_id == rounds[0].version_id
    # The builder is told that the change did not generalise, as a number and nothing more.
    attempt = builder.requests[-1]["payload"]["attempt_history"][-1]
    assert attempt["promoted"] is False and attempt["score"] > attempt["unseen_score"] == 0.25
    cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.suite_id == created["suite_id"])))
    unseen = [json.dumps(case.input["text"]) for case in cases if case.split != "development"]
    sent = json.dumps([request["payload"] for request in builder.requests])
    assert not any(text in sent for text in unseen)
    assert job.checkpoint["validation_scorecard"]["score"] == 0.25


def test_one_unseen_case_better_is_not_an_improvement_but_a_clear_net_gain_is():
    from factory.evaluation import can_promote

    def card(passed):
        rates = {f"s{n}": [int(n < passed), 1] for n in range(20)}
        score = passed / 20
        return {
            "total": 20,
            "score": score,
            "critical_failures": 0,
            "metrics": {"safety": 1, "approval_compliance": 1},
            "mean_latency_ms": 1,
            "cost": 0,
            "regression_outcomes": {},
            "case_rates": rates,
            "selection_cases": list(rates),
            "splits": {"selection": {"score": score, "total": 20, "passed": passed}},
        }

    assert can_promote(card(10)) is True
    assert can_promote(card(11), card(10)) is False
    assert can_promote(card(12), card(10)) is True
    assert can_promote(card(10), card(10)) is False and can_promote(card(9), card(10)) is False
    # Three gained and one lost is a net of two against a spread of two: still within chance.
    mixed = card(10)
    for name, value in (("s10", 1), ("s11", 1), ("s12", 1), ("s0", 0)):
        mixed["case_rates"][name] = [value, 1]
    mixed["score"] = mixed["splits"]["selection"]["score"] = 12 / 20
    assert can_promote(mixed, card(10)) is False
