"""Client for the sandbox service and the capability loop that runs a builder-written tool.

The sandbox executes code and nothing else. Every capability the code asks for is performed here, by the
caller-supplied broker, which is the runtime's existing permission-checked tool path. The sandbox is reached
over a Unix socket; it has no network and never connects to anything.
"""

import json

import httpx

from factory.config import settings

MAX_CAPABILITY_CALLS = 8
MAX_INPUT_BYTES = 200_000
MAX_RESULT_BYTES = 2_000_000
REQUEST_TIMEOUT = 10


class SandboxUnavailable(RuntimeError):
    """No sandbox is configured or it cannot be reached. Generated code is never run in-process instead."""


class GeneratedToolError(ValueError):
    """The tool ran and failed. The message is the tool's own error, safe to show to a model."""


def sandbox_client():
    path = settings().sandbox_socket
    if not path:
        raise SandboxUnavailable("Generated tools require the sandbox service (SANDBOX_SOCKET is not set)")
    return httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=path),
        base_url="http://sandbox",
        timeout=REQUEST_TIMEOUT,
        trust_env=False,
    )


async def sandbox_available():
    try:
        async with sandbox_client() as client:
            return (await client.get("/health")).status_code == 200
    except (SandboxUnavailable, httpx.HTTPError, OSError):
        return False


async def run_generated_tool(code, tool_input, broker):
    """Run tool code to completion. `broker(capability, arguments)` performs one capability and returns JSON data.

    A broker exception that is a permission failure propagates and ends the run. Any other broker failure is
    recorded as an error result, which the tool sees as a ValueError and may handle.
    """
    if len(json.dumps(tool_input, default=str)) > MAX_INPUT_BYTES:
        raise GeneratedToolError("Tool input exceeds the size limit")
    results = []
    try:
        async with sandbox_client() as client:
            for _ in range(MAX_CAPABILITY_CALLS + 1):
                body = json.dumps({"code": code, "input": tool_input, "results": results})
                if len(body) > MAX_RESULT_BYTES:
                    raise GeneratedToolError("Capability results exceed the size limit")
                response = await client.post("/run", content=body, headers={"Content-Type": "application/json"})
                if response.status_code != 200:
                    raise SandboxUnavailable(f"Sandbox returned HTTP {response.status_code}")
                outcome = response.json()
                status = outcome.get("status")
                if status == "ok":
                    return outcome["output"]
                if status == "error":
                    raise GeneratedToolError(str(outcome.get("error", "Tool failed"))[:400])
                if status != "needs_capability" or outcome.get("index") != len(results):
                    raise SandboxUnavailable("Sandbox broke the run protocol")
                request = outcome["request"]
                try:
                    result = await broker(request["capability"], request["arguments"])
                    results.append({"request": request, "result": result})
                except PermissionError:
                    raise
                except Exception as error:
                    results.append({"request": request, "error": f"{type(error).__name__}: {str(error)[:200]}"})
    except PermissionError:
        # PermissionError is an OSError. A denied capability must never be reported as an outage.
        raise
    except (httpx.HTTPError, OSError) as error:
        raise SandboxUnavailable(f"Sandbox is unreachable: {type(error).__name__}") from None
    raise GeneratedToolError("Tool made too many capability calls")
