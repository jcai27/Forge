import hashlib
import hmac
import io
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select

from factory.api import app, limits
from factory.connectors import EmailConnector, FileConnector, MCPConnector, RESTConnector, safe_url
from factory.db import get_db
from factory.models import DataSource
from factory.security import token_for


@pytest.fixture
def client(db, seeded):
    app.dependency_overrides[get_db] = lambda: db
    limits.clear()
    org, user, *_ = seeded
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + token_for(user.id, org.id)
        yield client
    app.dependency_overrides.clear()


def test_ssrf_rejects_private_destinations_and_unapproved_hosts(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="Private"):
        safe_url("https://approved.example", ["approved.example"])
    with pytest.raises(ValueError, match="authorized"):
        safe_url("https://other.example", ["approved.example"])
    with pytest.raises(ValueError):
        safe_url("https://user:pass@approved.example", ["approved.example"])


@pytest.mark.asyncio
async def test_rest_connector_invokes_real_http_contract_with_mock_transport(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))])
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer test-credential"
        return httpx.Response(200, json={"records": [{"sku": "SKU-001"}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    connector = RESTConnector(
        {
            "base_url": "https://approved.example",
            "allowed_hosts": ["approved.example"],
            "operations": [{"name": "catalog", "description": "Read catalog", "path": "/catalog", "method": "GET"}],
        },
        "test-credential",
    )
    result = await connector.invoke("catalog", {"limit": 10})
    assert result["records"][0]["sku"] == "SKU-001"
    assert calls[0].url.path == "/catalog"
    assert calls[0].url.params["limit"] == "10"
    with pytest.raises(ValueError):
        await connector.invoke("unregistered", {})


@pytest.mark.asyncio
async def test_file_xlsx_and_csv_resource_scope():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["sku", "price"])
    sheet.append(["SKU-001", 250])
    output = io.BytesIO()
    workbook.save(output)
    records = FileConnector.parse(output.getvalue(), "catalog.xlsx")
    assert records == [{"sku": "SKU-001", "price": 250}]
    assert FileConnector.parse(b"sku,price\nSKU-002,100\n", "catalog.csv")[0]["sku"] == "SKU-002"
    adapter = FileConnector({}, records={"approved": records})
    assert (await adapter.invoke("read_file", {"resource": "approved"}))["records"] == records
    with pytest.raises(ValueError):
        await adapter.invoke("read_file", {"resource": "private"})


@pytest.mark.asyncio
async def test_email_explicit_mock_and_mcp_adapter(monkeypatch):
    adapter = EmailConnector({"provider": "mock"})
    assert (await adapter.invoke("read_inbox", {}))["messages"]
    response = await adapter.invoke("send_email", {"to": "a@example.invalid", "subject": "Schedule", "body": "Confirm"})
    assert response["mode"] == "mock"
    from types import SimpleNamespace

    class Server:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def list_tools(self):
            return [SimpleNamespace(name="read_catalog", inputSchema={"type": "object"}, description="Read")]

        async def call_tool(self, name, arguments):
            return SimpleNamespace(model_dump=lambda **kw: {"content": [{"type": "text", "text": "data"}]})

    connector = MCPConnector({"allowed_tools": ["read_catalog"], "read_tools": ["read_catalog"]})
    monkeypatch.setattr(connector, "server", lambda: Server())
    discovered = await connector.discover()
    assert discovered[0]["write"] is False
    assert (await connector.invoke("read_catalog", {}))["content"]
    with pytest.raises(ValueError):
        await connector.invoke("send_message", {})


def test_signed_webhook_is_authenticated_idempotent_and_private(client, db, seeded):
    result = client.post("/integrations", json={"name": "Inbound orders", "kind": "webhook", "secret": "signing-key"})
    assert result.status_code == 201
    connection_id = result.json()["id"]
    timestamp = str(int(time.time()))
    body = json.dumps({"text": "Harbor Bistro: 2 kg Tomatoes"}).encode()
    signature = hmac.new(b"signing-key", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"X-Webhook-Timestamp": timestamp, "X-Webhook-Signature": signature, "Content-Type": "application/json"}
    assert client.post(f"/webhooks/{connection_id}", content=body).status_code == 401
    assert client.post(f"/webhooks/{connection_id}", content=body, headers=headers).json()["duplicate"] is False
    assert client.post(f"/webhooks/{connection_id}", content=body, headers=headers).json()["duplicate"] is True
    source = db.scalar(select(DataSource).where(DataSource.connection_id == connection_id))
    assert source.model_visible is False
    assert len(source.records) == 1


@pytest.mark.asyncio
async def test_postgres_connector_discovers_allowed_table_and_enforces_read_only(db):
    from sqlalchemy import Column, Integer, MetaData, String, Table

    from factory.connectors import PostgreSQLConnector

    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Executed by the PostgreSQL verification suite")
    schema = db.get_bind().get_execution_options()["schema_translate_map"][None]
    table = Table(
        "connector_catalog", MetaData(schema=schema), Column("sku", String, primary_key=True), Column("stock", Integer)
    )
    table.create(db.get_bind())
    db.execute(table.insert().values(sku="SKU-001", stock=150))
    db.commit()
    dsn = db.get_bind().url.set(drivername="postgresql").render_as_string(hide_password=False)
    connector = PostgreSQLConnector({"schema": schema, "tables": ["connector_catalog"]}, dsn)
    resources = await connector.discover()
    assert [r["name"] for r in resources] == ["connector_catalog"]
    assert (await connector.invoke("read_table", {"table": "connector_catalog", "limit": 1}))["records"] == [
        {"sku": "SKU-001", "stock": 150}
    ]
    with pytest.raises(ValueError, match="denied"):
        await connector.invoke("read_table", {"table": "users"})
    import psycopg
    from psycopg import sql

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with connector.connect() as connection:
            connection.execute(
                sql.SQL("INSERT INTO {}.{} VALUES (%s,%s)").format(
                    sql.Identifier(schema), sql.Identifier("connector_catalog")
                ),
                ("SKU-002", 50),
            )
