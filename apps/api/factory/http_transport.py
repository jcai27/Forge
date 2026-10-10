"""Origin-scoped HTTP transport with public DNS resolution pinned to the socket."""

import asyncio
import ipaddress
import socket
import ssl
import time
import zlib
from functools import partial
from urllib.parse import urlparse

import httpcore
import httpx
import httpx2


def validate_url(url, allowed_hosts):
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or parsed.username is not None or parsed.password is not None:
        raise ValueError("Only credential-free HTTP(S) URLs are supported")
    host = (parsed.hostname or "").encode("idna").decode().lower()
    approved = {host.encode("idna").decode().lower() for host in allowed_hosts}
    if not host or host not in approved:
        raise ValueError("Host is not explicitly authorized")
    if parsed.fragment:
        raise ValueError("HTTP fragments are not supported")
    return url


def public_addresses(addresses):
    result = []
    blocked = [ipaddress.ip_network(net) for net in ("64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "2002::/16")]
    for address in addresses:
        text = address[4][0]
        ip = ipaddress.ip_address(text)
        if "%" in text or not ip.is_global or any(ip in network for network in blocked):
            raise ValueError("Private, loopback, transition and metadata network destinations are forbidden")
        if str(ip) not in result:
            result.append(str(ip))
    if not result:
        raise ValueError("Host has no approved public address")
    return result


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, host, port, delegate=None):
        self.host, self.port = host, port
        self.delegate = delegate or httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host != self.host or port != self.port:
            raise ValueError("Connection origin is not authorized")
        duration = min(timeout, 15) if timeout is not None else 15
        deadline = time.monotonic() + duration
        try:
            async with asyncio.timeout(duration):
                resolved = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
                addresses = public_addresses(resolved)
                for address in addresses:
                    try:
                        # A numeric address cannot undergo a second hostname resolution.
                        return await self.delegate.connect_tcp(
                            address,
                            port,
                            timeout=max(0, deadline - time.monotonic()),
                            local_address=local_address,
                            socket_options=socket_options,
                        )
                    except httpcore.ConnectError:
                        continue
                raise httpcore.ConnectError("No approved public address could be connected")
        except TimeoutError:
            raise httpcore.ConnectTimeout("HTTP connection deadline exceeded") from None
        except OSError:
            raise httpcore.ConnectError("Public HTTP host resolution failed") from None

    async def connect_unix_socket(self, *args, **kwargs):
        raise ValueError("Unix socket egress is forbidden")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream, request, headers=(), client_library=httpx):
        self.stream, self.request, self.client_library = stream, request, client_library
        self.headers = headers

    async def __aiter__(self):
        try:
            async for chunk in self.stream:
                yield chunk
        except (httpcore.TimeoutException, httpcore.NetworkError, httpcore.ProtocolError) as error:
            error_type = getattr(self.client_library, type(error).__name__, self.client_library.TransportError)
            raise error_type("Connector HTTP stream failed", request=self.request) from None

    async def aclose(self):
        await self.stream.aclose()


class PinnedHTTPTransport(httpx.AsyncBaseTransport):
    def __init__(
        self, url, allowed_hosts, backend=None, ssl_context=None, client_library=httpx, stream_class=ResponseStream
    ):
        validate_url(url, allowed_hosts)
        self.origin = httpx.URL(url).copy_with(path="/", query=None, fragment=None)
        self.allowed_hosts = allowed_hosts
        self.client_library, self.stream_class = client_library, stream_class
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context or ssl.create_default_context(),
            retries=0,
            network_backend=backend
            or PinnedNetworkBackend(
                self.origin.raw_host.decode(), self.origin.port or (443 if self.origin.scheme == "https" else 80)
            ),
            max_connections=10,
            max_keepalive_connections=5,
        )

    async def handle_async_request(self, request):
        validate_url(str(request.url), self.allowed_hosts)
        if (request.url.scheme, request.url.raw_host, request.url.port) != (
            self.origin.scheme,
            self.origin.raw_host,
            self.origin.port,
        ):
            raise ValueError("Cross-origin connector request is forbidden")
        # Never accept an override that changes TLS identity independently of the URL.
        if request.extensions.get("sni_hostname") not in (None, self.origin.raw_host.decode()):
            raise ValueError("TLS hostname override is forbidden")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = await self.pool.handle_async_request(core_request)
        except (httpcore.TimeoutException, httpcore.NetworkError, httpcore.ProtocolError) as error:
            error_type = getattr(self.client_library, type(error).__name__, self.client_library.TransportError)
            raise error_type("Connector HTTP transport failed", request=request) from None
        try:
            stream = self.stream_class(response.stream, request, response.headers)
        except Exception:
            await response.aclose()
            raise
        return self.client_library.Response(
            response.status,
            headers=stream.headers,
            stream=stream,
            extensions=response.extensions,
        )

    async def aclose(self):
        await self.pool.aclose()


def pinned_client(url, allowed_hosts, **kwargs):
    # Proxy environment and redirects cannot bypass the validated connection backend.
    return httpx.AsyncClient(
        transport=PinnedHTTPTransport(url, allowed_hosts), trust_env=False, follow_redirects=False, **kwargs
    )


class MCPResponseBudget:
    """One shared response budget across initialization, pagination and SSE streams."""

    def __init__(self, limit=2_000_000):
        self.limit, self.wire, self.decoded = limit, 0, 0
        self.deadline = time.monotonic() + 15


class MCPResponseStream(httpx2.AsyncByteStream):
    def __init__(self, stream, request, headers=(), budget=None):
        self.stream = ResponseStream(stream, request, headers, httpx2)
        self.budget = budget or MCPResponseBudget()
        metadata = httpx2.Headers(headers)
        length = metadata.get("Content-Length")
        if length is not None:
            try:
                advertised = int(length)
            except ValueError:
                raise httpx2.StreamError("Invalid MCP response length") from None
            if advertised < 0 or advertised > self.budget.limit - self.budget.wire:
                raise httpx2.StreamError("MCP response exceeds wire budget")
        encoding = metadata.get("Content-Encoding", "identity").strip().lower()
        if encoding not in ("identity", "gzip", "deflate"):
            raise httpx2.StreamError("Unsupported MCP response encoding")
        self.decoder = (
            zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS)
            if encoding != "identity"
            else None
        )
        # Decode before HTTPX2/SSE parsing, preventing its automatic unbounded decoder.
        self.headers = [
            (key, value) for key, value in headers if key.lower() not in (b"content-encoding", b"content-length")
        ]

    async def __aiter__(self):
        try:
            iterator = aiter(self.stream)
            while True:
                try:
                    # Keep cancellation scopes inside reads, never across generator yields.
                    async with asyncio.timeout(max(0, self.budget.deadline - time.monotonic())):
                        chunk = await anext(iterator)
                except StopAsyncIteration:
                    break
                if self.budget.decoded > self.budget.limit:
                    raise httpx2.StreamError("MCP response exceeds decoded budget")
                self.budget.wire += len(chunk)
                if self.budget.wire > self.budget.limit:
                    raise httpx2.StreamError("MCP response exceeds wire budget")
                if self.decoder:
                    try:
                        chunk = self.decoder.decompress(chunk, self.budget.limit - self.budget.decoded + 1)
                    except zlib.error:
                        raise httpx2.StreamError("Invalid compressed MCP response") from None
                    if self.decoder.unused_data:
                        raise httpx2.StreamError("Trailing compressed MCP response")
                self.budget.decoded += len(chunk)
                if self.budget.decoded > self.budget.limit:
                    raise httpx2.StreamError("MCP response exceeds decoded budget")
                yield chunk
            if self.decoder and (not self.decoder.eof or self.decoder.unused_data):
                raise httpx2.StreamError("Incomplete or trailing compressed MCP response")
        except TimeoutError:
            raise httpx2.ReadTimeout("MCP session deadline exceeded", request=self.stream.request) from None
        finally:
            await self.aclose()

    async def aclose(self):
        await self.stream.aclose()


class MCPPinnedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, url, allowed_hosts, **kwargs):
        self.budget = MCPResponseBudget()
        self.inner = PinnedHTTPTransport(
            url,
            allowed_hosts,
            client_library=httpx2,
            stream_class=partial(MCPResponseStream, budget=self.budget),
            **kwargs,
        )

    async def handle_async_request(self, request):
        remaining = self.budget.deadline - time.monotonic()
        if remaining <= 0:
            raise httpx2.ReadTimeout("MCP session deadline exceeded", request=request)
        try:
            async with asyncio.timeout(remaining):
                return await self.inner.handle_async_request(request)
        except TimeoutError:
            raise httpx2.ReadTimeout("MCP session deadline exceeded", request=request) from None

    async def aclose(self):
        await self.inner.aclose()


def pinned_mcp_client(url, allowed_hosts, **kwargs):
    # MCP 2 uses httpx2; its transport/stream types are independent of HTTPX 0.x.
    return httpx2.AsyncClient(
        transport=MCPPinnedTransport(url, allowed_hosts), trust_env=False, follow_redirects=False, **kwargs
    )
