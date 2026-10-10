"""Origin-scoped HTTP transport with public DNS resolution pinned to the socket."""

import asyncio
import ipaddress
import socket
import ssl
import time
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
    def __init__(self, stream, request, client_library=httpx):
        self.stream, self.request, self.client_library = stream, request, client_library

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
        return self.client_library.Response(
            response.status,
            headers=response.headers,
            stream=self.stream_class(response.stream, request),
            extensions=response.extensions,
        )

    async def aclose(self):
        await self.pool.aclose()


def pinned_client(url, allowed_hosts, **kwargs):
    # Proxy environment and redirects cannot bypass the validated connection backend.
    return httpx.AsyncClient(
        transport=PinnedHTTPTransport(url, allowed_hosts), trust_env=False, follow_redirects=False, **kwargs
    )


class MCPResponseStream(httpx2.AsyncByteStream):
    def __init__(self, stream, request):
        self.stream = ResponseStream(stream, request, httpx2)

    async def __aiter__(self):
        async for chunk in self.stream:
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class MCPPinnedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, url, allowed_hosts, **kwargs):
        self.inner = PinnedHTTPTransport(
            url, allowed_hosts, client_library=httpx2, stream_class=MCPResponseStream, **kwargs
        )

    async def handle_async_request(self, request):
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()


def pinned_mcp_client(url, allowed_hosts, **kwargs):
    # MCP 2 uses httpx2; its transport/stream types are independent of HTTPX 0.x.
    return httpx2.AsyncClient(
        transport=MCPPinnedTransport(url, allowed_hosts), trust_env=False, follow_redirects=False, **kwargs
    )
