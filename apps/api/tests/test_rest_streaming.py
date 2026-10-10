import asyncio
import gzip
import json
import socket
import zlib

import httpx
import pytest

from factory.connectors import RESTConnector


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks, self.delay = chunks, delay
        self.reads, self.closed = 0, False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def connector(monkeypatch, handler, method="GET"):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))])
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))
    return RESTConnector(
        {
            "base_url": "https://approved.example",
            "allowed_hosts": ["approved.example"],
            "operations": [
                {"name": "operation", "description": "Bounded operation", "path": "/operation", "method": method}
            ],
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["advertised", "chunked", "gzip_bomb", "unsupported", "truncated"])
async def test_rest_rejects_oversized_or_invalid_streams_and_closes_them(monkeypatch, kind):
    headers = {}
    if kind == "advertised":
        headers["Content-Length"] = "2000001"
        chunks = [b"x" * 65536] * 100
    elif kind == "chunked":
        chunks = [b"x" * 65536] * 100
    elif kind == "gzip_bomb":
        headers["Content-Encoding"] = "gzip"
        chunks = [gzip.compress(json.dumps({"message": "x" * 4_000_000}).encode())]
    elif kind == "unsupported":
        headers["Content-Encoding"] = "br"
        chunks = [b"not-consumed"]
    else:
        headers["Content-Encoding"] = "gzip"
        chunks = [gzip.compress(b'{"ok":true}')[:-4]]
    stream = TrackedStream(chunks)
    adapter = connector(monkeypatch, lambda request: httpx.Response(200, headers=headers, stream=stream))
    with pytest.raises(ValueError):
        await adapter.invoke("operation", {})
    assert stream.closed
    if kind in ("advertised", "unsupported"):
        assert stream.reads == 0
    elif kind == "chunked":
        assert stream.reads == 31 and stream.reads < len(chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
async def test_rest_parses_valid_compressed_json_without_httpx_unbounded_decompression(monkeypatch, encoding):
    expected = {"records": [{"name": "Customer", "quantity": 12}]}
    encoded = (gzip.compress if encoding == "gzip" else zlib.compress)(json.dumps(expected).encode())
    stream = TrackedStream([encoded[i : i + 10] for i in range(0, len(encoded), 10)])
    adapter = connector(
        monkeypatch, lambda request: httpx.Response(200, headers={"Content-Encoding": encoding}, stream=stream)
    )
    assert await adapter.invoke("operation", {}) == expected
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_rest_retries_only_reads_and_never_consumes_rate_limit_bodies(monkeypatch, method):
    calls, streams, delays = [], [], []

    async def sleep(delay):
        delays.append(delay)

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            stream = TrackedStream([b"x" * 65536] * 100)
            streams.append(stream)
            return httpx.Response(429, headers={"Retry-After": "nan"}, stream=stream)
        return httpx.Response(200, json={"accepted": True})

    adapter = connector(monkeypatch, handler, method)
    monkeypatch.setattr("factory.connectors.asyncio.sleep", sleep)
    if method == "GET":
        assert await adapter.invoke("operation", {}) == {"accepted": True}
        assert len(calls) == 2 and delays == [1]
    else:
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.invoke("operation", {})
        assert len(calls) == 1 and delays == []
    assert streams[0].closed and streams[0].reads == 0


@pytest.mark.asyncio
async def test_rest_total_deadline_stops_a_trickling_body_and_closes_it(monkeypatch):
    stream = TrackedStream([b"{"], delay=0.05)
    adapter = connector(monkeypatch, lambda request: httpx.Response(200, stream=stream))
    monkeypatch.setattr("factory.connectors.REST_REQUEST_TIMEOUT", 0.01)
    with pytest.raises(TimeoutError):
        await adapter.invoke("operation", {})
    assert stream.closed and stream.reads == 0
