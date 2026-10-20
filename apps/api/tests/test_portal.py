"""The customer side: a workspace of its own, an installed agent, documents arriving and their results."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from factory.config import settings
from factory.db import now
from factory.models import (
    AgentVersion,
    Channel,
    Deployment,
    ExecutionRun,
    InboxDocument,
    Membership,
    Operation,
    Organization,
    UsageRecord,
)
from factory.portal import check_channel, ingest, insights, mailbox_tick
from factory.security import token_for
from tests.test_documents import pdf, upload
from tests.test_intake import Model, client, direct_agent, member, reply, user_text  # noqa: F401


def invoice(number, day, price, supplier="Gordon Food Service", total_cents=None):
    """A typed invoice whose answer is printed on it, so a scripted agent can read it off."""
    answer = {
        "supplier": supplier,
        "customer": "STEEL CITY DINER",
        "invoice_number": str(number),
        "invoice_date": day,
        "total_cents": round(price * 500) if total_cents is None else total_cents,
        "items": [
            {
                "code": "206539",
                "description": "CASE LARGE EGGS",
                "quantity": 5,
                "unit_price": price,
                "amount": round(price * 5, 2),
            },
        ],
    }
    return pdf([f"INVOICE {number}", "DATA " + json.dumps(answer, separators=(",", ":"))]), answer


class InvoiceAgent(Model):
    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs
    ):
        payload = json.loads(user_text(input))
        text = payload.get("input", payload)["text"]
        return reply(json.loads(text.split("DATA ", 1)[1].splitlines()[0]))

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


@pytest.fixture
def workspace(client, seeded, db, monkeypatch):  # noqa: F811
    """A builder with a deployed invoice agent, a customer workspace with it installed, and a customer's login."""
    org, user, *_ = seeded
    monkeypatch.setattr(settings(), "execution_mode", "live")
    monkeypatch.setattr(settings(), "openai_api_key", "local-provider-contract-only")
    from factory.runtime import reconstruct_agent

    def bind(context, mode):
        built = reconstruct_agent(context, mode)
        built.model = InvoiceAgent()
        return built

    monkeypatch.setattr("factory.runtime.reconstruct_agent", bind)
    created = direct_agent(client, seeded, request="Record each supplier invoice in full")
    rows = []
    for n in range(24):
        _, answer = invoice(1000 + n, f"2026-01-{n + 1:02d}", 9.0 + n)
        rows.append({"text": f"invoice text {n}", **{f"expected_{key}": value for key, value in answer.items()}})
    attached = client.post(
        f"/agents/{created['id']}/datasets",
        json={
            "name": "Invoices",
            "content": "\n".join(json.dumps(row) for row in rows),
            "format": "jsonl",
            "development": 8,
            "selection": 0,
            "validation": 8,
        },
    )
    assert attached.status_code == 201, attached.text
    version = db.get(AgentVersion, attached.json()["version"]["id"])
    version.approved_at, version.approved_by = now(), user.id
    deployment = Deployment(org_id=org.id, agent_id=created["id"], version_id=version.id, policy={"max_cost": 1})
    db.add(deployment)
    db.commit()
    customer = client.post("/customers", json={"name": "Steel City Diner"})
    assert customer.status_code == 201, customer.text
    installed = client.post(
        f"/customers/{customer.json()['id']}/operations",
        json={"deployment_id": deployment.id, "name": "Supplier invoices"},
    )
    assert installed.status_code == 201, installed.text
    there = db.get(Organization, customer.json()["id"])
    operation = db.scalar(select(Operation).where(Operation.org_id == there.id))
    return {
        "org": there,
        "operation": operation,
        "builder_there": {"Authorization": "Bearer " + token_for(user.id, there.id)},
        "customer": member(db, there, "customer"),
        "deployment": deployment,
    }


def test_a_customer_workspace_is_a_tenant_of_its_own_with_a_copy_of_the_approved_agent(client, seeded, db, workspace):  # noqa: F811
    org, *_ = seeded
    there, operation = workspace["org"], workspace["operation"]
    assert (there.kind, there.parent_org_id) == ("customer", org.id) and there.id != org.id
    placed = db.get(Deployment, operation.deployment_id)
    copy = db.get(AgentVersion, placed.version_id)
    source = db.get(AgentVersion, workspace["deployment"].version_id)
    # The copy is the approved version exactly, in the customer's tenant, with its own deployment and limits.
    assert (placed.org_id, copy.org_id) == (there.id, there.id) and copy.id != source.id and copy.spec == source.spec
    assert copy.approved_at and placed.policy["lifetime_max_cost"] == 50 and operation.document_field == "text"
    assert operation.source["version_id"] == source.id
    listed = client.get("/customers").json()["items"]
    assert [item["name"] for item in listed] == ["Steel City Diner"] and listed[0]["operations"][0][
        "name"
    ] == "Supplier invoices"
    # A customer workspace cannot open another, and only an active approved deployment can be installed.
    assert client.post("/customers", headers=workspace["builder_there"], json={"name": "Nested"}).status_code == 409
    workspace["deployment"].active = False
    db.commit()
    again = client.post(
        f"/customers/{there.id}/operations", json={"deployment_id": workspace["deployment"].id, "name": "Again"}
    )
    assert again.status_code == 409


def test_the_customer_role_reaches_the_portal_and_nothing_of_the_builders_side(client, seeded, db, workspace):  # noqa: F811
    _, _, agent, *_ = seeded
    customer = workspace["customer"]
    me = client.get("/portal/me", headers=customer)
    assert me.status_code == 200 and me.json()["role"] == "customer" and me.json()["can_work"]
    assert me.json()["operations"][0]["fields"]["tables"] == {
        "items": ["code", "description", "quantity", "unit_price", "amount"]
    }
    assert client.get("/auth/me", headers=customer).status_code == 200
    # The agent's design, its examples, runs, members and the builder's customer list are all closed to them,
    # in their own workspace as much as anywhere.
    for method, path in (
        ("get", "/agents"),
        ("get", f"/agents/{agent.id}"),
        ("get", "/runs"),
        ("get", "/organizations/members"),
        ("get", "/customers"),
        ("post", "/documents/text"),
        ("get", "/audit"),
    ):
        assert client.request(method, path, headers=customer).status_code == 403, path
    assert (
        client.post(
            f"/customers/{workspace['org'].id}/invitations", headers=customer, json={"email": "a@b.co"}
        ).status_code
        == 403
    )
    invited = client.post(f"/customers/{workspace['org'].id}/invitations", json={"email": "owner@diner.example"})
    assert invited.status_code == 201 and invited.json()["role"] == "customer" and invited.json()["token"]


def test_an_uploaded_document_is_read_run_through_the_agent_and_kept_with_its_pages(client, seeded, db, workspace):  # noqa: F811
    customer, operation = workspace["customer"], workspace["operation"]
    data, answer = invoice(131862443, "2026-02-01", 9.37)
    url = f"/portal/operations/{operation.id}/documents"
    made = client.post(url, headers=customer, files=upload(data, "gfs-131862443.pdf"))
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["status"] == "processed" and body["answer"] == answer and not body["duplicate"]
    assert body["fields"]["invoice_number"] == "131862443" and body["rows"] == {"items": 1} and body["pages"] == 1
    # The page is kept as an image, typed though it is, and only this workspace can fetch it.
    page = client.get(f"/portal/pages/{body['page_ids'][0]}", headers=customer)
    assert page.status_code == 200 and page.content[:4] == b"\x89PNG"
    assert client.get(f"/portal/pages/{body['page_ids'][0]}").status_code == 404
    assert client.get(f"/portal/documents/{body['id']}").status_code == 404
    # It ran through the production queue of the customer's own deployment, charged in the customer's workspace.
    document = db.get(InboxDocument, body["id"])
    assert document.run_id and db.get(Deployment, operation.deployment_id).spent >= 0
    assert db.scalar(select(UsageRecord).where(UsageRecord.org_id == workspace["org"].id)) is not None
    # The same file again is the same document.
    again = client.post(url, headers=customer, files=upload(data, "copy.pdf")).json()
    assert again["id"] == body["id"] and again["duplicate"]
    listed = client.get(url, headers=customer).json()
    assert listed["total"] == 1 and listed["items"][0]["name"] == "gfs-131862443.pdf"
    # What cannot be taken in says so; a viewer cannot upload.
    assert client.post(url, headers=customer, files=upload(b"hello", "note.txt")).status_code == 422
    viewer = member(db, workspace["org"], "viewer")
    assert client.post(url, headers=viewer, files=upload(data, "x.pdf")).status_code == 403
    assert client.get(url, headers=viewer).status_code == 200


def test_a_person_can_correct_an_answer_and_the_agents_own_is_kept(client, seeded, db, workspace):  # noqa: F811
    customer, operation = workspace["customer"], workspace["operation"]
    data, answer = invoice(77, "2026-02-01", 9.37)
    made = client.post(
        f"/portal/operations/{operation.id}/documents", headers=customer, files=upload(data, "a.pdf")
    ).json()
    url = f"/portal/documents/{made['id']}/review"
    fixed = {**answer, "invoice_number": "78"}
    reviewed = client.post(url, headers=customer, json={"corrected": fixed})
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["answer"]["invoice_number"] == "78" and body["agent_answer"]["invoice_number"] == "77"
    assert body["reviewed"] and body["corrected"]
    # A correction must still be an answer of the agent's shape.
    assert client.post(url, headers=customer, json={"corrected": {"supplier": 5}}).status_code == 422
    assert client.post(url, headers=member(db, workspace["org"], "viewer"), json={}).status_code == 403


def test_prices_are_watched_in_code_from_the_recorded_lines_and_exported(client, seeded, db, workspace):  # noqa: F811
    customer, operation = workspace["customer"], workspace["operation"]
    url = f"/portal/operations/{operation.id}"
    for number, day, price in ((1, "2026-02-01", 9.37), (2, "2026-02-08", 10.47), (3, "2026-02-15", 10.60)):
        made = client.post(
            f"{url}/documents", headers=customer, files=upload(invoice(number, day, price)[0], f"{number}.pdf")
        )
        assert made.json()["status"] == "processed", made.text
    seen = client.get(f"{url}/insights", headers=customer).json()
    # 9.37 to 10.47 is 11.7% up: a rise. 10.47 to 10.60 is 1.2%: not one.
    assert seen["applies"] and seen["documents"] == 3 and seen["failed"] == 0
    assert seen["stages"] == {"review": 0, "ready": 3, "approved": 0, "exported": 0}
    (rise,) = seen["price_rises"]
    assert (rise["last_price"], rise["price"], rise["rise_percent"], rise["date"]) == (9.37, 10.47, 11.7, "2026-02-08")
    assert seen["spend"] == [{"supplier": "Gordon Food Service", "documents": 3, "total_cents": 4685 + 5235 + 5300}]
    exported = client.get(f"{url}/export.csv", headers=customer)
    lines = exported.text.strip().splitlines()
    assert exported.headers["content-type"].startswith("text/csv") and len(lines) == 4
    assert "invoice_number" in lines[0] and "unit_price" in lines[0] and "CASE LARGE EGGS" in lines[1]
    # Nothing in documents that are not invoices to watch.
    assert insights([]) == {
        "applies": False,
        "documents": 0,
        "price_rises": [],
        "extra_cents": 0,
        "spend": [],
        "threshold_percent": 5.0,
    }


async def test_documents_arrive_from_a_mailbox_and_an_inbound_address(client, seeded, db, workspace, monkeypatch):  # noqa: F811
    customer, operation = workspace["customer"], workspace["operation"]
    url = f"/portal/operations/{operation.id}/channels"
    # A mailbox is opened once when it is connected, to prove the details and note where it stands.
    monkeypatch.setattr("factory.portal.mailbox_position", lambda config, password: {"validity": 7, "uid": 40})
    details = {"kind": "mailbox", "name": "Invoices inbox", "host": "imap.example.com", "username": "ap@diner.example"}
    assert client.post(url, headers=customer, json=details).status_code == 422
    made = client.post(url, headers=customer, json={**details, "password": "app-password"})
    assert made.status_code == 201, made.text
    assert "password" not in json.dumps(made.json()) and made.json()["has_secret"]
    channel = db.get(Channel, made.json()["id"])
    assert channel.cursor == {"validity": 7, "uid": 40} and "app-password" not in channel.encrypted_secret

    calls = []

    def fetch(config, password, cursor, limit):
        calls.append((config["host"], password, dict(cursor)))
        files = [
            {"name": "inv-9.pdf", "sender": "billing@gfs.example", "data": invoice(9, "2026-03-01", 9.0)[0]},
            {"name": "logo.gif", "sender": "billing@gfs.example", "data": b"GIF89a not a document"},
        ]
        return {"validity": 7, "uid": 42}, files

    assert await mailbox_tick(lambda: _same(db), fetch) == 1
    assert calls == [("imap.example.com", "app-password", {"validity": 7, "uid": 40})]
    document = db.scalar(select(InboxDocument).where(InboxDocument.source == "mailbox"))
    assert (document.status, document.sender, document.channel_id) == ("processed", "billing@gfs.example", channel.id)
    db.refresh(channel)
    # The position moved on, the attachment that is not a document is named, and the mailbox is not due again yet.
    assert channel.cursor == {"validity": 7, "uid": 42} and "logo.gif" in channel.last_error
    assert await mailbox_tick(lambda: _same(db), fetch) == 0 and len(calls) == 1

    # An inbound address takes a file from another system on the strength of its key alone.
    issued = client.post(url, headers=customer, json={"kind": "inbound", "name": "From the scanner"}).json()
    assert issued["key"] and issued["address"] == f"/portal/inbound/{issued['id']}"
    posted = client.post(
        issued["address"],
        headers={"Authorization": "Bearer " + issued["key"]},
        files=upload(invoice(10, "2026-03-02", 9.1)[0], "scan.pdf"),
        data={"sender": "front-office scanner"},
    )
    assert posted.status_code == 201 and posted.json()["status"] == "processed"
    for key in ("wrong-key", ""):
        refused = client.post(
            issued["address"], headers={"Authorization": "Bearer " + key}, files=upload(b"%PDF-1.4", "x.pdf")
        )
        assert refused.status_code == 404
    listed = client.get(url, headers=customer).json()["items"]
    assert [item["kind"] for item in listed] == ["mailbox", "inbound"] and "key" not in json.dumps(listed)
    # Results go out to https addresses only.
    for bad in ("http://hooks.example/in", "https://user:pw@hooks.example/in"):
        assert (
            client.post(url, headers=customer, json={"kind": "webhook", "name": "Books", "url": bad}).status_code == 422
        )
    assert (
        client.post(
            url, headers=customer, json={"kind": "webhook", "name": "Books", "url": "https://hooks.example/in"}
        ).status_code
        == 201
    )


async def test_an_email_body_is_taken_in_as_text(client, seeded, db, workspace, monkeypatch):  # noqa: F811
    customer, operation = workspace["customer"], workspace["operation"]
    url = f"/portal/operations/{operation.id}/channels"
    monkeypatch.setattr("factory.portal.mailbox_position", lambda config, password: {"validity": 7, "uid": 40})
    details = {"kind": "mailbox", "name": "Bodies", "host": "imap.example.com", "username": "ap@diner.example"}
    plain = client.post(url, headers=customer, json={**details, "password": "app-password"}).json()
    assert plain["config"]["read_body"] is False
    made = client.post(url, headers=customer, json={**details, "password": "app-password", "read_body": True})
    assert made.status_code == 201 and made.json()["config"]["read_body"] is True
    channel = db.get(Channel, made.json()["id"])

    answer = invoice(11, "2026-03-03", 9.5)[1]
    body = "INVOICE 11\nDATA " + json.dumps(answer, separators=(",", ":"))

    def fetch(config, password, cursor, limit):
        item = {"name": "Email body", "sender": "billing@gfs.example", "text": body}
        return {"validity": 7, "uid": 41}, [item, dict(item)]

    assert await check_channel(db, channel, fetch) == 1
    documents = list(db.scalars(select(InboxDocument).where(InboxDocument.source == "mailbox")))
    assert len(documents) == 1
    assert documents[0].pages == [{"text": body}] and documents[0].status == "processed"
    assert db.get(ExecutionRun, documents[0].run_id).input == {operation.document_field: body}
    # The same text again is the same document.
    channel.cursor = {"validity": 7, "uid": 40}
    assert await check_channel(db, channel, fetch) == 0
    assert db.scalar(select(func.count()).select_from(InboxDocument).where(InboxDocument.source == "mailbox")) == 1
    # The manual upload stays PDF and image only.
    upload_url = f"/portal/operations/{operation.id}/documents"
    assert client.post(upload_url, headers=customer, files=upload(body.encode(), "note.txt")).status_code == 422
    # A paused operation takes nothing in.
    operation.enabled = False
    db.commit()
    with pytest.raises(HTTPException) as paused:
        await ingest(db, operation, b"", "Email body", "mailbox", text="Another email")
    assert paused.value.status_code == 409


class _same:
    """Hand the tick the test's own session, as a context manager that leaves it open."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *args):
        return False


def test_one_customer_cannot_see_another(client, seeded, db, workspace):  # noqa: F811
    customer, operation = workspace["customer"], workspace["operation"]
    made = client.post(
        f"/portal/operations/{operation.id}/documents",
        headers=customer,
        files=upload(invoice(5, "2026-02-01", 9.0)[0], "a.pdf"),
    ).json()
    other = client.post("/customers", json={"name": "Another Cafe"}).json()
    rival = member(db, db.get(Organization, other["id"]), "customer")
    for path in (
        f"/portal/documents/{made['id']}",
        f"/portal/operations/{operation.id}/documents",
        f"/portal/operations/{operation.id}/insights",
        f"/portal/operations/{operation.id}/export.csv",
        f"/portal/operations/{operation.id}/channels",
        f"/portal/pages/{made['page_ids'][0]}",
    ):
        assert client.get(path, headers=rival).status_code == 404, path
    assert client.get("/portal/me", headers=rival).json()["operations"] == []
    # The builder's hold on a customer's workspace is its membership there: without it, nothing.
    membership = db.scalar(
        select(Membership).where(Membership.org_id == workspace["org"].id, Membership.role == "admin")
    )
    db.delete(membership)
    db.commit()
    assert [item["name"] for item in client.get("/customers").json()["items"]] == ["Another Cafe"]
    assert client.post(f"/customers/{workspace['org'].id}/invitations", json={"email": "a@b.co"}).status_code == 404


def test_someone_invited_as_a_customer_signs_in_to_that_workspace(client, seeded, db, workspace):  # noqa: F811
    invited = client.post(f"/customers/{workspace['org'].id}/invitations", json={"email": "owner@diner.example"}).json()
    account = {"email": "owner@diner.example", "password": "a-long-password"}
    joined = client.post("/auth/register", json={**account, "organization": "Personal"}).json()
    own = {"Authorization": "Bearer " + joined["token"]}
    accepted = client.post("/organization-invitations/accept", headers=own, json={"token": invited["token"]})
    assert accepted.status_code == 200, accepted.text
    # They have two workspaces now: the one registration made, and the customer's. Signing in opens the customer's.
    session = client.post("/auth/login", json=account).json()
    assert session["organization"]["id"] == workspace["org"].id and session["user"]["email"] == account["email"]
    me = client.get("/portal/me", headers={"Authorization": "Bearer " + session["token"]}).json()
    assert me["role"] == "customer" and me["operations"][0]["name"] == "Supplier invoices"


def send(client, workspace, number, day, price, name=None, **more):  # noqa: F811
    made = client.post(
        f"/portal/operations/{workspace['operation'].id}/documents",
        headers=workspace["customer"],
        files=upload(invoice(number, day, price, **more)[0], name or f"{number}.pdf"),
    )
    assert made.status_code == 201 and made.json()["status"] == "processed", made.text
    return made.json()


def test_the_checks_decide_which_invoices_need_a_person(client, seeded, db, workspace):  # noqa: F811
    customer = workspace["customer"]
    clean = send(client, workspace, 1, "2026-02-01", 9.37)
    assert (clean["stage"], clean["exceptions"], clean["exception_list"]) == ("ready", 0, [])
    # A total that is not what the lines add up to: tax, perhaps, or a misread figure. A person decides.
    off = send(client, workspace, 2, "2026-02-02", 9.40, total_cents=4999)
    assert off["stage"] == "review" and [item["kind"] for item in off["exception_list"]] == ["lines_do_not_add_up"]
    assert off["exception_list"][0]["difference_cents"] == 299
    # The same invoice number from the same supplier in a different file.
    twice = send(client, workspace, 1, "2026-02-01", 9.38, name="again.pdf")
    kinds = {item["kind"]: item for item in twice["exception_list"]}
    assert twice["stage"] == "review" and kinds["duplicate"]["document_id"] == clean["id"]
    # Ten times last week's price is a misread decimal far more often than a fact.
    odd = send(client, workspace, 3, "2026-02-08", 93.7)
    assert [item["kind"] for item in odd["exception_list"]] == ["price_looks_misread"]
    url = f"/portal/operations/{workspace['operation'].id}"
    assert client.get(f"{url}/insights", headers=customer).json()["price_rises"] == []
    # The misread price is not taken as the last price paid either: the next invoice is compared with the real one.
    after = send(client, workspace, 4, "2026-02-15", 10.47)
    assert after["stage"] == "ready"
    (rise,) = client.get(f"{url}/insights", headers=customer).json()["price_rises"]
    assert (rise["last_price"], rise["price"], rise["extra_cents"]) == (9.4, 10.47, 535)
    # Filtering the inbox by where documents stand.
    waiting = client.get(f"{url}/documents?stage=review", headers=customer).json()
    assert waiting["total"] == 3 and {item["stage"] for item in waiting["items"]} == {"review"}
    # Approving what the checks passed leaves the rest for a person.
    assert client.post(f"{url}/approve-ready", headers=customer).json() == {"approved": 2}
    stages = client.get(f"{url}/insights", headers=customer).json()["stages"]
    assert stages == {"review": 3, "ready": 0, "approved": 2, "exported": 0}
    # A person who corrects the figure clears what the check raised; approving records who did.
    line = {**odd["answer"]["items"][0], "unit_price": 9.37, "amount": 46.85}
    fixed = {**odd["answer"], "items": [line], "total_cents": 4685}
    done = client.post(f"/portal/documents/{odd['id']}/review", headers=customer, json={"corrected": fixed}).json()
    assert (done["stage"], done["exception_list"], done["approved_automatically"]) == ("approved", [], False)
    assert client.post(f"{url}/approve-ready", headers=member(db, workspace["org"], "viewer")).status_code == 403


def test_clean_invoices_can_be_approved_without_a_person_when_the_customer_chooses(client, seeded, db, workspace):  # noqa: F811
    customer, url = workspace["customer"], f"/portal/operations/{workspace['operation'].id}"
    saved = client.put(f"{url}/settings", headers=customer, json={"auto_approve_clean": True})
    assert saved.status_code == 200 and saved.json()["auto_approve_clean"]
    clean = send(client, workspace, 1, "2026-02-01", 9.37)
    assert clean["stage"] == "approved" and clean["approved_automatically"]
    # What the checks flag still waits for a person, whatever the setting.
    assert send(client, workspace, 2, "2026-02-02", 9.40, total_cents=1)["stage"] == "review"


def test_approved_invoices_go_to_the_books_once_coded_to_an_account(client, seeded, db, workspace):  # noqa: F811
    customer, url = workspace["customer"], f"/portal/operations/{workspace['operation'].id}"
    first = send(client, workspace, 1, "2026-02-01", 9.37)
    send(client, workspace, 2, "2026-02-02", 9.40, total_cents=4999)
    assert client.post(f"{url}/exports", headers=customer, json={"format": "xero"}).status_code == 409
    client.post(f"{url}/approve-ready", headers=customer)
    # Nothing goes to the books without a ledger account to code it to.
    refused = client.post(f"{url}/exports", headers=customer, json={"format": "xero"})
    assert refused.status_code == 422 and "Gordon Food Service" in refused.json()["error"]["message"]
    accounts = [{"code": "5000", "name": "Food cost"}, {"code": "5100", "name": "Produce"}]
    bad = client.put(f"{url}/settings", headers=customer, json={"accounts": accounts, "default_account": "9999"})
    assert bad.status_code == 422
    settings = {
        "accounts": accounts,
        "default_account": "5100",
        "supplier_accounts": {"Gordon Food Service": "5000"},
        "terms_days": 28,
    }
    saved = client.put(f"{url}/settings", headers=customer, json=settings).json()
    assert saved["suppliers"] == ["Gordon Food Service"] and "xero" in saved["formats"]
    # Xero's template needs a tax type on every line: without one the file would be refused on import, so it is not made.
    untaxed = client.post(f"{url}/exports", headers=customer, json={"format": "xero"})
    assert untaxed.status_code == 422 and "tax type" in untaxed.json()["error"]["message"]
    client.put(f"{url}/settings", headers=customer, json={**settings, "tax_code": "Tax Exempt (0%)"})
    waiting = client.get(f"{url}/exports", headers=customer).json()
    assert (waiting["waiting"], waiting["uncoded_suppliers"], waiting["items"]) == (1, [], [])
    batch = client.post(f"{url}/exports", headers=customer, json={"format": "xero"})
    assert batch.status_code == 201 and batch.json()["documents"] == 1
    lines = client.get(f"/portal/exports/{batch.json()['id']}/file", headers=customer).text.strip().splitlines()
    assert lines[0].startswith("*ContactName,*InvoiceNumber,*InvoiceDate,*DueDate")
    # The supplier's account, the due date from the terms, and a bill that adds up to the invoice.
    # Dates month first unless the customer chooses otherwise.
    assert lines[1] == "Gordon Food Service,1,02/01/2026,03/01/2026,206539 CASE LARGE EGGS,5,9.37,5000,Tax Exempt (0%)"
    # It went once: the document is marked, cannot be changed here, and is not sent again.
    gone = client.get(f"/portal/documents/{first['id']}", headers=customer).json()
    assert gone["stage"] == "exported" and gone["export_id"] == batch.json()["id"]
    assert client.post(f"/portal/documents/{first['id']}/review", headers=customer, json={}).status_code == 409
    assert client.post(f"{url}/exports", headers=customer, json={"format": "xero"}).status_code == 409
    # Another customer cannot fetch the file.
    other = client.post("/customers", json={"name": "Another Cafe"}).json()
    rival = member(db, db.get(Organization, other["id"]), "customer")
    assert client.get(f"/portal/exports/{batch.json()['id']}/file", headers=rival).status_code == 404


def test_negative_amounts_are_exported_as_numbers_and_formula_text_is_guarded():
    import csv
    import io
    from decimal import Decimal
    from types import SimpleNamespace

    from factory.payables import export_file

    starts = ["=1+1", "+1", "-1", "@SUM(A1)", "\tcmd", "\rcmd"]
    answer = {
        "supplier": "Sample Produce",
        "invoice_number": "12",
        "invoice_date": "2026-02-01",
        "total_cents": 1150,
        "items": [
            {"description": "Carrots", "quantity": 2, "unit_price": 5, "amount": 10.0},
            {"description": "Onions", "quantity": 1, "unit_price": 5, "amount": 5.0},
        ]
        + [{"description": text, "quantity": 1, "unit_price": 0, "amount": 0.0} for text in starts],
    }
    document = SimpleNamespace(corrected=None, output=answer, name="12.pdf")
    settings = {"default_account": "5000", "tax_code": "Tax on Purchases"}
    # The lines add up to more than the invoice: the balancing line is a negative number, not text.
    xero = list(csv.reader(io.StringIO(export_file("xero", [document], settings), newline="")))
    assert xero[-1][4] == "Tax and charges not on a line" and xero[-1][6] == "-3.50"
    quickbooks = list(csv.reader(io.StringIO(export_file("quickbooks", [document], settings), newline="")))
    assert quickbooks[-1][6] == "-3.50"
    assert sum(Decimal(row[6]) for row in quickbooks[1:]) * 100 == 1150
    # Text that a spreadsheet would run, or that starts with a tab or carriage return, is still guarded.
    for rows, column in ((xero, 4), (quickbooks, 5)):
        assert [row[column] for row in rows[3:-1]] == ["'" + text for text in starts]


def test_a_bill_always_adds_up_to_the_invoice_and_weights_are_one_unit():
    from types import SimpleNamespace

    from factory.payables import bill_lines, export_file

    answer = {
        "supplier": "Gordon Food Service",
        "invoice_number": "77",
        "invoice_date": "2026-02-01",
        "total_cents": 16000,
        "items": [
            {"code": "1", "description": "CS # BEEF GRND 61.40 LB", "quantity": 1, "unit_price": 1.6, "amount": 98.24},
            {"code": "2", "description": "CASE EGGS", "quantity": 5, "unit_price": 9.37, "amount": 46.85},
            {"description": "=SUM(A1)", "quantity": 1, "unit_price": 2.21, "amount": 2.21},
        ],
    }
    document = SimpleNamespace(corrected=None, output=answer, name="77.pdf")
    header, lines = bill_lines(document, {"default_account": "5000", "terms_days": 14})
    assert header["due"] == "2026-02-15" and header["account"] == "5000"
    # Sold by weight: one unit at the line's amount. And the $12.70 the invoice charges beyond its lines.
    shown = [(str(quantity), str(price)) for _, quantity, price, _ in lines]
    assert shown == [("1", "98.24"), ("5", "9.37"), ("1", "2.21"), ("1", "12.70")]
    assert sum(amount for *_, amount in lines) * 100 == 16000
    quickbooks = export_file("quickbooks", [document], {"default_account": "5000"}).splitlines()
    # The headings are QuickBooks' own names for its mandatory bill fields.
    assert quickbooks[0] == "Bill no.,Supplier,Bill Date,Due Date,Account,Line Description,Line Amount,Line Tax Code"
    assert len(quickbooks) == 5
    # A description a spreadsheet would run as a formula is written as text.
    assert "'=SUM(A1)" in quickbooks[3]
    # Dates are written the way the customer's accounting system is set to read them.
    assert bill_lines(document, {"date_format": "dmy", "terms_days": 14})[0]["due"] == "15/02/2026"
    assert bill_lines(document, {"date_format": "mdy", "terms_days": 14})[0]["date"] == "02/01/2026"
    # QuickBooks takes fewer than 1,000 rows and at most 100 bills in a file: the rest wait for the next one.
    from factory.payables import quickbooks_batch, unsendable

    many = [SimpleNamespace(corrected=None, output=answer, name=f"{n}.pdf") for n in range(400)]
    first = quickbooks_batch(many, {"default_account": "5000"})
    assert len(first) == 100 and len(export_file("quickbooks", first, {"default_account": "5000"}).splitlines()) == 401
    long = {
        **answer,
        "total_cents": 150000,
        "items": [{"description": "x", "quantity": 1, "unit_price": 5, "amount": 5.0}] * 300,
    }
    heavy = [SimpleNamespace(corrected=None, output=long, name=f"{n}.pdf") for n in range(10)]
    assert len(quickbooks_batch(heavy, {})) == 3  # 300 lines a bill: three fit under a thousand rows with the heading
    # It takes no bill below zero, and Xero none without a tax type.
    credit = SimpleNamespace(corrected=None, output={**answer, "total_cents": -500}, name="credit.pdf")
    assert "credit.pdf" in unsendable("quickbooks", [document, credit], {})
    assert (
        unsendable("quickbooks", [document], {}) is None
        and unsendable("xero", [document], {"tax_code": "NONE"}) is None
    )
    assert "tax type" in unsendable("xero", [document], {})


def test_a_suppliers_statement_is_reconciled_against_the_invoices_received(client, seeded, db, workspace):  # noqa: F811
    customer, org, operation = workspace["customer"], workspace["org"], workspace["operation"]
    send(client, workspace, 101, "2026-02-01", 9.37)
    send(client, workspace, 102, "2026-02-08", 10.0)
    send(client, workspace, 103, "2026-02-10", 11.0)
    statements = Operation(
        org_id=org.id,
        deployment_id=operation.deployment_id,
        actor_id=operation.actor_id,
        name="Supplier statements",
        document_field="text",
        kind="statement",
    )
    db.add(statements)
    db.flush()
    rows = [
        {"invoice_number": "0101", "invoice_date": "2026-02-01", "amount": 46.85},
        {"invoice_number": "102", "invoice_date": "2026-02-08", "amount": 55.0},
        {"invoice_number": "104", "invoice_date": "2026-02-12", "amount": 20.0},
    ]
    statement = InboxDocument(
        org_id=org.id,
        operation_id=statements.id,
        source="upload",
        name="statement.pdf",
        content_hash="s" * 64,
        status="processed",
        stage="ready",
        output={"supplier": "Gordon Food Service", "rows": rows},
    )
    db.add(statement)
    db.commit()
    found = client.get(f"/portal/documents/{statement.id}/reconciliation", headers=customer).json()
    # 101 agrees, leading zero and all. 102 is on file for $50.00, not $55.00. 104 never arrived. 103 arrived
    # within the statement's dates and the supplier does not list it.
    assert [row["status"] for row in found["rows"]] == ["matched", "amount_differs", "not_received"]
    assert found["rows"][1]["our_amount"] == 50.0 and found["counts"]["not_on_statement"] == 1
    assert found["not_on_statement"][0]["invoice_number"] == "103" and found["statement_total"] == 121.85
    # Only a statement can be reconciled, and only by its own workspace.
    invoices = client.get(f"/portal/operations/{operation.id}/documents", headers=customer).json()["items"]
    assert client.get(f"/portal/documents/{invoices[0]['id']}/reconciliation", headers=customer).status_code == 404
    assert client.get(f"/portal/documents/{statement.id}/reconciliation").status_code == 404


def test_tax_makes_the_lines_add_up_and_goes_on_a_line_of_its_own():
    from types import SimpleNamespace

    from factory.payables import bill_lines, check

    line = {"code": "1", "description": "CASE EGGS", "quantity": 5, "unit_price": 9.37, "amount": 46.85}
    answer = {
        "supplier": "S",
        "invoice_number": "1",
        "invoice_date": "2026-02-01",
        "total_cents": 5013,
        "tax_cents": 328,
        "items": [line],
    }
    document = SimpleNamespace(
        id="a", corrected=None, output=answer, name="1.pdf", status="processed", created_at=1, approved_by=None
    )
    assert check(document, [document]) == []
    header, lines = bill_lines(document, {"default_account": "5000"})
    assert [(text, str(amount)) for text, _, _, amount in lines] == [("1 CASE EGGS", "46.85"), ("Tax", "3.28")]
    # With the tax recorded, a total that still does not add up is a misread figure, and says so.
    document.output = {**answer, "tax_cents": 0}
    (found,) = check(document, [document])
    assert (
        found["kind"] == "lines_do_not_add_up"
        and found["difference_cents"] == 328
        and "tax is $0.00" in found["message"]
    )


def test_a_better_version_replaces_the_agent_and_reads_what_nobody_has_approved_again(client, seeded, db, workspace):  # noqa: F811
    org, user, *_ = seeded
    customer, operation = workspace["customer"], workspace["operation"]
    kept = send(client, workspace, 1, "2026-02-01", 9.37)
    again = send(client, workspace, 2, "2026-02-02", 9.40)
    client.post(f"/portal/documents/{kept['id']}/review", headers=customer, json={})
    old = db.get(Deployment, operation.deployment_id)
    # The builder approves and deploys a new version of its own agent, and puts it behind the customer's operation.
    source = db.get(Deployment, workspace["deployment"].id)
    version = db.get(AgentVersion, source.version_id)
    newer = AgentVersion(
        org_id=org.id,
        agent_id=version.agent_id,
        number=version.number + 1,
        spec=version.spec,
        approved_at=now(),
        approved_by=user.id,
    )
    db.add(newer)
    db.flush()
    deployed = Deployment(org_id=org.id, agent_id=version.agent_id, version_id=newer.id, policy={"max_cost": 1})
    db.add(deployed)
    db.commit()
    url = f"/customers/{workspace['org'].id}/operations/{operation.id}/upgrade"
    done = client.post(url, json={"deployment_id": deployed.id})
    assert done.status_code == 200, done.text
    # Only the document nobody had approved was read again, from its stored page; the approved one was left.
    assert done.json()["reprocessed"] == 1 and done.json()["operations"][0]["source"]["version"] == newer.number
    db.refresh(operation)
    db.refresh(old)
    placed = db.get(Deployment, operation.deployment_id)
    assert placed.id != old.id and placed.active and not old.active and placed.org_id == workspace["org"].id
    assert db.get(AgentVersion, placed.version_id).number == 2
    first, second = db.get(InboxDocument, kept["id"]), db.get(InboxDocument, again["id"])
    db.refresh(first)
    db.refresh(second)
    assert first.run_id == kept["run_id"] and second.run_id != again["run_id"] and second.status == "processed"
    # A customer cannot upgrade an operation, and an approved document is not read again on request.
    assert client.post(url, headers=customer, json={"deployment_id": deployed.id}).status_code == 403
    assert client.post(f"/portal/documents/{kept['id']}/reprocess", headers=customer).status_code == 409
    assert client.post(f"/portal/documents/{again['id']}/reprocess", headers=customer).status_code == 200


def test_the_overview_says_what_the_work_added_up_to(client, seeded, db, workspace):  # noqa: F811
    customer, url = workspace["customer"], f"/portal/operations/{workspace['operation'].id}"
    send(client, workspace, 1, "2026-02-02", 9.37)
    send(client, workspace, 2, "2026-02-09", 10.47)
    send(client, workspace, 3, "2026-02-10", 9.40, total_cents=4999)
    seen = client.get(f"{url}/overview", headers=customer).json()
    assert (seen["invoices"], seen["lines"], seen["pages"], seen["failed"]) == (3, 3, 3, 0)
    # Two needed nobody; one was flagged, and it says for what.
    assert (seen["clean"], seen["flagged"], seen["caught"]) == (2, 1, {"lines_do_not_add_up": 1})
    assert (seen["from"], seen["to"], seen["billed_cents"]) == ("2026-02-02", "2026-02-10", 4685 + 5235 + 4999)
    assert seen["by_place"] == [{"name": "STEEL CITY DINER", "total_cents": 14919}]
    assert seen["by_week"] == [
        {"week": "2026-02-02", "total_cents": 4685},
        {"week": "2026-02-09", "total_cents": 10234},
    ]
    # The eggs went up once, by $1.10 a case on five cases.
    assert (seen["price_rises"], seen["extra_cents"]) == (1, 550)
    assert seen["movers"][0]["description"] == "CASE LARGE EGGS" and seen["movers"][0]["extra_cents"] == 550
    assert seen["statements"]["count"] == 0
    other = client.post("/customers", json={"name": "Another Cafe"}).json()
    rival = member(db, db.get(Organization, other["id"]), "customer")
    assert client.get(f"{url}/overview", headers=rival).status_code == 404


def test_the_same_item_at_two_prices_on_one_day_is_found_and_money_is_added_up():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from factory.payables import overview, price_gaps

    def invoice_at(number, place, day, price, quantity=5):
        line = {
            "code": "50200",
            "description": "CASE KETCHUP",
            "quantity": quantity,
            "unit_price": price,
            "amount": round(price * quantity, 2),
        }
        data = {
            "supplier": "Gordon Food Service",
            "customer": place,
            "invoice_number": str(number),
            "invoice_date": day,
            "total_cents": round(price * quantity * 100),
            "tax_cents": 0,
            "items": [line],
        }
        return SimpleNamespace(
            id=str(number),
            name=f"{number}.pdf",
            output=data,
            corrected=None,
            status="processed",
            stage="ready",
            exceptions=[],
            pages=[{}],
            approved_by=None,
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
        )

    documents = [
        invoice_at(1, "DINER", "2026-02-02", 33.79),
        invoice_at(2, "CAFE", "2026-02-02", 43.75, quantity=2),
        invoice_at(3, "EXPRESS", "2026-02-02", 34.00),
        # Two days later at a higher price: that is a price moving, not one location charged more than
        # another, and it is not compared with Monday's.
        invoice_at(4, "TRUCK STOP", "2026-02-04", 45.00),
        invoice_at(5, "CAFE", "2026-02-11", 44.00),
    ]
    (gap,) = price_gaps(documents)
    # The cafe paid $9.96 a case more than the diner the same day, on two cases. Under 2% apart is not a gap.
    assert (gap["customer"], gap["lowest_at"], gap["price"], gap["lowest_price"]) == ("CAFE", "DINER", 43.75, 33.79)
    assert (gap["above_percent"], gap["extra_cents"], gap["day"]) == (29.5, 1992, "2026-02-02")
    # The cafe's second delivery that day at the same price is the same finding, on two lines.
    (gap,) = price_gaps([*documents, invoice_at(8, "CAFE", "2026-02-02", 43.75, quantity=1)])
    assert (gap["lines"], gap["extra_cents"]) == (2, 2988)
    statement = {
        "counts": {"matched": 3, "not_received": 1, "amount_differs": 1, "not_on_statement": 0},
        "rows": [
            {"status": "not_received", "amount": 1521.8},
            {"status": "amount_differs", "amount": 60.0, "our_amount": 50.0},
            {"status": "matched", "amount": 10.0, "our_amount": 10.0},
        ],
    }
    seen = overview(documents, [statement])
    found = {row["kind"]: (row["cents"], row["count"]) for row in seen["found"]}
    # An invoice the statement lists that is not on file is reported, with its amount, but is not money found.
    assert found == {"statement_overbilled": (1000, 1), "price_gaps": (1992, 1)}
    assert (seen["statements"]["not_received"], seen["statements"]["not_received_cents"]) == (1, 152180)
    assert seen["found_cents"] == 2992 and seen["days"] == 10 and seen["price_gap_count"] == 1
    # The cafe's own last price was $40.00, so the same two cases are also a rise of $7.50. That is the
    # same overpayment seen a second way: it stays with the gap and adds nothing to the total. The
    # truck stop's rise, on a day nobody else bought, is counted on its own.
    earlier = [invoice_at(6, "CAFE", "2026-02-01", 40.00), invoice_at(7, "TRUCK STOP", "2026-02-01", 40.00)]
    seen = overview(earlier + documents, [statement])
    found = {row["kind"]: (row["cents"], row["count"]) for row in seen["found"]}
    assert seen["extra_cents"] == 750 + 2500
    assert found["price_gaps"] == (1992, 1) and found["price_rises"] == (2500, 2)
    assert seen["found_cents"] == 2992 + 2500


def test_the_dashboard_adds_up_what_came_in_by_day_location_and_item():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from factory.payables import analytics

    def invoice(number, place, day, lines):
        items = [
            {"code": code, "description": name, "quantity": quantity, "unit_price": price, "amount": quantity * price}
            for code, name, quantity, price in lines
        ]
        data = {
            "supplier": "Gordon Food Service",
            "customer": place,
            "invoice_number": str(number),
            "invoice_date": day,
            "total_cents": round(sum(item["amount"] for item in items) * 100),
            "items": items,
        }
        return SimpleNamespace(
            id=str(number),
            output=data,
            corrected=None,
            approved_by=None,
            exceptions=[],
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
        )

    documents = [
        invoice(1, "DINER", "2026-02-02", [("50200", "CASE KETCHUP", 2, 30.0), ("70001", "CASE EGGS", 5, 10.0)]),
        invoice(2, "CAFE", "2026-02-02", [("50200", "CASE KETCHUP", 1, 32.0)]),
        invoice(3, "DINER", "2026-02-05", [("70001", "CASE EGGS", 4, 12.0)]),
    ]
    seen = analytics(documents)
    assert (seen["invoices"], seen["spend_cents"], seen["lines"], seen["quantity"], seen["items"]) == (
        3,
        19000,
        4,
        12,
        2,
    )
    # Every day in the range is there, including the two on which nothing came in.
    assert [(row["start"], row["total_cents"], row["quantity"]) for row in seen["series"]] == [
        ("2026-02-02", 14200, 8),
        ("2026-02-03", 0, 0),
        ("2026-02-04", 0, 0),
        ("2026-02-05", 4800, 4),
    ]
    assert (seen["days"], seen["delivery_days"], seen["bucket"]) == (4, 2, "day")
    assert [(row["name"], row["total_cents"], row["invoices"]) for row in seen["by_place"]] == [
        ("DINER", 15800, 2),
        ("CAFE", 3200, 1),
    ]
    eggs, ketchup = seen["top_items"]
    assert (eggs["description"], eggs["quantity"], eggs["total_cents"], eggs["times"], eggs["places"]) == (
        "CASE EGGS",
        9,
        9800,
        2,
        1,
    )
    assert (eggs["low_price"], eggs["high_price"], eggs["last_price"]) == (10.0, 12.0, 12.0)
    assert (ketchup["quantity"], ketchup["total_cents"], ketchup["places"]) == (3, 9200, 2)
    # The diner's eggs went from $10 to $12: one rise, on four cases.
    assert (seen["price_rises"], seen["price_rise_cents"]) == (1, 800)
    # One location alone: its own figures, with the whole list of locations still offered.
    cafe = analytics(documents, "CAFE")
    assert (cafe["invoices"], cafe["spend_cents"], cafe["places"], cafe["place"]) == (
        1,
        3200,
        ["CAFE", "DINER"],
        "CAFE",
    )
