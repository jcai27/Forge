import asyncio
import contextlib
import json
import socket
import ssl
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpcore
import httpx
import httpx2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from factory.connectors import MCPConnector
from factory.http_transport import MCPPinnedTransport, PinnedHTTPTransport, PinnedNetworkBackend


@asynccontextmanager
async def tls_fixture(tmp_path, certificate_host="approved.example"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, certificate_host)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(certificate_host)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "fixture-cert.pem", tmp_path / "fixture-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    key_path.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    sni, requests = [], []
    context.set_servername_callback(lambda sock, name, ctx: sni.append(name))

    async def handle(reader, writer):
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            lines = header.decode().split("\r\n")
            headers = {
                line.split(":", 1)[0].lower(): line.split(":", 1)[1].strip() for line in lines[1:] if ":" in line
            }
            body = await reader.readexactly(int(headers.get("content-length", 0)))
            message = json.loads(body) if body else {}
            requests.append((lines[0], headers, message))
            method = message.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": message["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "Local TLS MCP", "version": "1"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "read_catalog",
                            "description": "Fixture catalog",
                            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                        }
                    ]
                }
            elif method == "tools/call":
                result = {"content": [{"type": "text", "text": json.dumps({"sku": "SKU-001"})}], "isError": False}
            else:
                result = {"ok": True}
            status = "202 Accepted" if method and "id" not in message else "200 OK"
            payload = (
                b""
                if status.startswith("202")
                else json.dumps({"jsonrpc": "2.0", "id": message.get("id"), "result": result}).encode()
            )
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                + payload
            )
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=context)
    port = server.sockets[0].getsockname()[1]
    client_context = ssl.create_default_context(cafile=str(cert_path))

    class LocalFixtureSocket(httpcore.AsyncNetworkBackend):
        def __init__(self):
            self.connections = []

        async def connect_tcp(self, host, connected_port, **kwargs):
            # Only this test delegate maps the approved numeric IP to its owned fixture.
            assert host == "93.184.216.34" and connected_port == port
            self.connections.append((host, connected_port))
            return await httpcore.AnyIOBackend().connect_tcp("127.0.0.1", port, **kwargs)

    delegate = LocalFixtureSocket()
    try:
        yield port, client_context, delegate, sni, requests
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_certificate", [True, False])
async def test_real_tls_keeps_hostname_verification_on_a_pinned_socket(tmp_path, monkeypatch, valid_certificate):
    async with tls_fixture(tmp_path, "approved.example" if valid_certificate else "wrong.example") as (
        port,
        context,
        delegate,
        sni,
        requests,
    ):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, requested_port, **kwargs: [(2, 1, 6, "", ("93.184.216.34", requested_port))],
        )
        url = f"https://approved.example:{port}"
        backend = PinnedNetworkBackend("approved.example", port, delegate)
        transport = PinnedHTTPTransport(url, ["approved.example"], backend=backend, ssl_context=context)
        async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
            if valid_certificate:
                assert (await client.get(url)).status_code == 200
                assert requests[0][1]["host"] == f"approved.example:{port}"
            else:
                with pytest.raises(httpx.ConnectError):
                    await client.get(url)
                assert requests == []
        assert sni == ["approved.example"]


@pytest.mark.asyncio
async def test_actual_mcp_sdk_initializes_discovers_and_calls_over_pinned_tls(tmp_path, monkeypatch):
    async with tls_fixture(tmp_path) as (port, context, delegate, sni, requests):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, requested_port, **kwargs: [(2, 1, 6, "", ("93.184.216.34", requested_port))],
        )
        url = f"https://approved.example:{port}/mcp"

        def client_factory(configured_url, hosts, **kwargs):
            transport = MCPPinnedTransport(
                configured_url,
                hosts,
                backend=PinnedNetworkBackend("approved.example", port, delegate),
                ssl_context=context,
            )
            return httpx2.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, **kwargs)

        monkeypatch.setattr("factory.connectors.pinned_mcp_client", client_factory)
        connector = MCPConnector(
            {
                "url": url,
                "allowed_hosts": ["approved.example"],
                "allowed_tools": ["read_catalog"],
                "read_tools": ["read_catalog"],
            },
            secret="fictional-local-bearer",
        )
        discovered = await connector.discover()
        assert discovered[0]["name"] == "read_catalog" and discovered[0]["write"] is False
        result = await connector.invoke("read_catalog", {})
        assert json.loads(result["content"][0]["text"]) == {"sku": "SKU-001"}
        methods = [request[2].get("method") for request in requests]
        assert "initialize" in methods and "tools/list" in methods and "tools/call" in methods
        assert delegate.connections and all(name == "approved.example" for name in sni)
        assert all(request[1].get("authorization") == "Bearer fictional-local-bearer" for request in requests)
