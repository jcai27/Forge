import asyncio
import gzip
import json
import time
import zlib

import httpcore
import httpx2
import pytest

from factory.http_transport import MCPPinnedTransport


class TrackedBody:
    def __init__(self, chunks):
        self.chunks, self.reads, self.closed = chunks, 0, False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


class ResponsePool:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def handle_async_request(self, request):
        return next(self.responses)

    async def aclose(self):
        pass


def transport(responses):
    client_transport = MCPPinnedTransport("https://approved.example/mcp", ["approved.example"])
    client_transport.inner.pool = ResponsePool(responses)
    return client_transport


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["length", "negative_length", "invalid_length", "wire", "gzip_bomb", "encoding", "truncated", "trailing"]
)
async def test_mcp_transport_rejects_unbounded_invalid_bodies_and_closes_streams(kind):
    headers = []
    chunks = [b"x" * 65536] * 100
    if kind in ("length", "negative_length", "invalid_length"):
        headers = [
            (b"content-length", {"length": b"2000001", "negative_length": b"-1", "invalid_length": b"unknown"}[kind])
        ]
    elif kind == "gzip_bomb":
        headers = [(b"content-encoding", b"gzip")]
        chunks = [gzip.compress(b"x" * 4_000_000)]
    elif kind == "encoding":
        headers = [(b"content-encoding", b"br")]
    elif kind in ("truncated", "trailing"):
        headers = [(b"content-encoding", b"gzip")]
        compressed = gzip.compress(b'{"ok":true}')
        chunks = [compressed[:-4] if kind == "truncated" else compressed + b"extra"]
    body = TrackedBody(chunks)
    client_transport = transport([httpcore.Response(200, headers=headers, content=body)])
    async with httpx2.AsyncClient(transport=client_transport) as client:
        with pytest.raises(httpx2.StreamError):
            await client.get("https://approved.example/mcp")
    assert body.closed
    if kind in ("length", "negative_length", "invalid_length", "encoding"):
        assert body.reads == 0
    elif kind == "wire":
        assert body.reads == 31 < len(chunks)
    elif kind == "gzip_bomb":
        assert client_transport.budget.decoded == 2_000_001


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["identity", "gzip", "deflate"])
async def test_mcp_transport_decodes_bounded_chunks_before_native_parser(encoding):
    expected = {"content": [{"type": "text", "text": "Catalog"}]}
    original = json.dumps(expected).encode()
    encoded = {"identity": lambda data: data, "gzip": gzip.compress, "deflate": zlib.compress}[encoding](original)
    body = TrackedBody([encoded[i : i + 7] for i in range(0, len(encoded), 7)])
    client_transport = transport(
        [
            httpcore.Response(
                200,
                headers=[(b"content-encoding", encoding.encode()), (b"content-length", str(len(encoded)).encode())],
                content=body,
            )
        ]
    )
    async with httpx2.AsyncClient(transport=client_transport) as client:
        result = await client.get("https://approved.example/mcp")
        assert result.json() == expected
        assert "content-encoding" not in result.headers and "content-length" not in result.headers
    assert body.closed
    assert client_transport.budget.wire == len(encoded)
    assert client_transport.budget.decoded == len(original)


@pytest.mark.asyncio
async def test_mcp_session_budget_is_shared_across_sequential_and_open_streams():
    bodies = [TrackedBody([b"a" * 1_000_001]), TrackedBody([b"b" * 1_000_001])]
    client_transport = transport([httpcore.Response(200, content=body) for body in bodies])
    async with httpx2.AsyncClient(transport=client_transport) as client:
        async with client.stream("GET", "https://approved.example/mcp") as first:
            async with client.stream("GET", "https://approved.example/mcp") as second:
                assert len(await first.aread()) == 1_000_001
                with pytest.raises(httpx2.StreamError, match="wire budget"):
                    await second.aread()
    assert all(body.closed for body in bodies)


@pytest.mark.asyncio
async def test_exhausted_decoded_budget_cannot_enable_unbounded_decompression_on_another_stream():
    compressed = gzip.compress(b"x" * 4_000_000)
    bodies = [TrackedBody([compressed]), TrackedBody([compressed])]
    client_transport = transport(
        [httpcore.Response(200, headers=[(b"content-encoding", b"gzip")], content=body) for body in bodies]
    )
    async with httpx2.AsyncClient(transport=client_transport) as client:
        for _ in bodies:
            with pytest.raises(httpx2.StreamError, match="decoded budget"):
                await client.get("https://approved.example/mcp")
            assert client_transport.budget.decoded == 2_000_001
    assert all(body.closed for body in bodies)


@pytest.mark.asyncio
async def test_shared_session_deadline_closes_trickling_body_and_blocks_later_cleanup_dispatch():
    class Trickle(TrackedBody):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.005)
                self.reads += 1
                yield b"x"

    body, cleanup = Trickle([]), TrackedBody([b"cleanup"])
    client_transport = transport([httpcore.Response(200, content=body), httpcore.Response(200, content=cleanup)])
    client_transport.budget.deadline = time.monotonic() + 0.03
    async with httpx2.AsyncClient(transport=client_transport) as client:
        with pytest.raises(httpx2.ReadTimeout, match="session deadline"):
            await client.get("https://approved.example/mcp")
        with pytest.raises(httpx2.ReadTimeout, match="session deadline"):
            await client.delete("https://approved.example/mcp")
    assert body.closed and 0 < body.reads < 20
    assert cleanup.reads == 0  # Expired sessions never obtain another HTTP response.
