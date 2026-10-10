import asyncio
import socket
import time

import httpcore
import httpx
import httpx2
import pytest

from factory.connectors import MCPConnector, safe_url
from factory.http_transport import (
    MCPResponseStream,
    PinnedHTTPTransport,
    PinnedNetworkBackend,
    ResponseStream,
    pinned_client,
)


class RecordedStream(httpcore.AsyncMockStream):
    def __init__(self):
        super().__init__([b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}'])
        self.writes, self.tls = [], []

    async def write(self, buffer, timeout=None):
        self.writes.append(buffer)

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls.append((server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
        return self


class RecordedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self.calls, self.streams = [], []

    async def connect_tcp(self, host, port, **kwargs):
        self.calls.append((host, port))
        stream = RecordedStream()
        self.streams.append(stream)
        return stream


@pytest.mark.asyncio
async def test_connection_pins_resolved_ip_preserving_http_host_and_tls_identity(monkeypatch):
    resolutions = []

    def resolve(host, port, **kwargs):
        resolutions.append(host)
        # A second resolution would point at metadata. The socket receives a numeric IP.
        ip = "93.184.216.34" if len(resolutions) == 1 else "169.254.169.254"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    delegate = RecordedBackend()
    backend = PinnedNetworkBackend("approved.example", 443, delegate)
    transport = PinnedHTTPTransport("https://approved.example", ["approved.example"], backend=backend)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        assert (await client.get("https://approved.example/catalog")).json() == {"ok": True}
    assert resolutions == ["approved.example"]
    assert delegate.calls == [("93.184.216.34", 443)]
    stream = delegate.streams[0]
    assert stream.tls[0][0:2] == ("approved.example", True)
    assert b"Host: approved.example\r\n" in b"".join(stream.writes)
    assert stream._closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "64:ff9b::7f00:1", "2002:7f00:1::", "2606:4700::1111%lo0"],
)
async def test_connection_rejects_non_public_or_transition_dns_before_any_socket(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kwargs: [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
        ],
    )
    delegate = RecordedBackend()
    backend = PinnedNetworkBackend("approved.example", 443, delegate)
    with pytest.raises(ValueError):
        await backend.connect_tcp("approved.example", 443)
    assert delegate.calls == []


@pytest.mark.asyncio
async def test_connect_time_revalidation_blocks_a_host_changed_after_legacy_check(monkeypatch):
    calls = []

    def resolve(host, port, **kwargs):
        calls.append(host)
        return [(2, 1, 6, "", ("93.184.216.34" if len(calls) == 1 else "127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    assert safe_url("https://approved.example", ["approved.example"])
    delegate = RecordedBackend()
    with pytest.raises(ValueError):
        await PinnedNetworkBackend("approved.example", 443, delegate).connect_tcp("approved.example", 443)
    assert delegate.calls == []


@pytest.mark.asyncio
async def test_dns_timeout_is_async_bounded_and_does_not_open_a_socket(monkeypatch):
    def resolve(*args, **kwargs):
        time.sleep(0.05)
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    delegate = RecordedBackend()
    with pytest.raises(httpcore.ConnectTimeout):
        await PinnedNetworkBackend("approved.example", 443, delegate).connect_tcp("approved.example", 443, timeout=0.01)
    assert delegate.calls == []
    await asyncio.sleep(0.06)  # Let the owned resolver fixture finish; cancellation cannot open a socket later.
    assert delegate.calls == []


@pytest.mark.asyncio
async def test_transport_rejects_other_origins_and_disables_proxy_environment(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    delegate = RecordedBackend()
    transport = PinnedHTTPTransport("https://approved.example", ["approved.example", "other.example"], backend=delegate)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        for url in ["https://other.example/", "http://approved.example/", "https://approved.example:444/"]:
            with pytest.raises(ValueError, match="origin"):
                await client.get(url)
    assert delegate.calls == []
    async with pinned_client("https://approved.example", ["approved.example"]) as client:
        assert client._trust_env is False and client.follow_redirects is False


@pytest.mark.asyncio
async def test_mcp_factory_uses_compatible_pinned_native_client():
    from factory.http_transport import MCPPinnedTransport

    server = MCPConnector({"url": "https://approved.example/mcp", "allowed_hosts": ["approved.example"]}).server()
    async with server.params["httpx_client_factory"](headers={}, timeout=15, auth=None) as client:
        assert client.__class__.__module__.startswith("httpx2")
        assert isinstance(client._transport, MCPPinnedTransport)
        assert client.follow_redirects is False and client._trust_env is False


@pytest.mark.asyncio
async def test_mixed_dns_answers_reject_before_connecting_to_any_address(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", (ip, 443)) for ip in ["93.184.216.34", "10.0.0.1"]],
    )
    delegate = RecordedBackend()
    with pytest.raises(ValueError):
        await PinnedNetworkBackend("approved.example", 443, delegate).connect_tcp("approved.example", 443)
    assert delegate.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("library,stream_type", [(httpx, ResponseStream), (httpx2, MCPResponseStream)])
async def test_body_failures_use_client_native_errors_and_preserve_stream_closure(library, stream_type):
    class BrokenBody:
        closed = False

        async def __aiter__(self):
            yield b"partial"
            raise httpcore.ReadTimeout("Internal details")

        async def aclose(self):
            self.closed = True

    body = BrokenBody()
    request = library.Request("GET", "https://approved.example")
    response = library.Response(200, stream=stream_type(body, request), request=request)
    with pytest.raises(library.ReadTimeout, match="Connector HTTP stream failed") as error:
        await response.aread()
    assert error.value.request is request
    await response.aclose()
    assert body.closed
