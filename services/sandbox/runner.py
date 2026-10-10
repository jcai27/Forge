"""Runs one builder-written tool in a fresh process. Standard library only.

Protocol: one JSON object on stdin, one JSON object on stdout.
  in:  {"code": str, "input": object, "results": [{"request": {...}, "result": {...}} | {"request": {...}, "error": str}]}
  out: {"status": "ok", "output": object}
     | {"status": "needs_capability", "request": {"capability": str, "arguments": object}, "index": int}
     | {"status": "error", "error": str}

A capability is never performed here. The first call without a recorded result stops the run and reports
the request; the caller performs it and runs the tool again with the result recorded. Replayed calls must
match the recorded requests exactly, so a tool cannot change what it asked for after seeing an answer.
"""

import builtins
import copy
import json
import os
import sys
import types

MAX_STDIN = 4_000_000
MAX_OUTPUT = 200_000
MAX_CALLS = 8


def no_inspection():
    """Make this process non-dumpable so another process of the same user cannot ptrace or read it."""
    try:
        import ctypes

        ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE = 4
    except (OSError, AttributeError):
        pass  # not Linux: the container that provides isolation is Linux


def apply_limits():
    no_inspection()
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX
        return
    megabyte = 1024 * 1024
    wanted = [
        ("RLIMIT_CPU", 2),
        ("RLIMIT_AS", 512 * megabyte),
        ("RLIMIT_FSIZE", 0),
        ("RLIMIT_CORE", 0),
        ("RLIMIT_NPROC", 0),
        ("RLIMIT_NOFILE", 16),
    ]
    for name, value in wanted:
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            # Some platforms refuse a specific limit. The container limits still apply.
            pass


class Pending(BaseException):
    """Raised by call() when a capability has no recorded result. Not catchable as Exception."""


class Abort(BaseException):
    """The run broke the replay contract."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def emit(payload):
    data = json.dumps(payload).encode()
    if len(data) > MAX_OUTPUT:
        data = json.dumps({"status": "error", "error": "Tool output exceeds the size limit"}).encode()
    os.write(1, data)


def main():
    policy_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, policy_dir)
    import codepolicy

    sys.path.remove(policy_dir)
    raw = sys.stdin.buffer.read(MAX_STDIN + 1)
    if len(raw) > MAX_STDIN:
        return emit({"status": "error", "error": "Request exceeds the size limit"})
    try:
        payload = json.loads(raw)
        code, tool_input, results = payload["code"], payload.get("input"), payload.get("results", [])
        if not isinstance(results, list):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return emit({"status": "error", "error": "Malformed sandbox request"})
    apply_limits()
    try:
        tree = codepolicy.check(code)
    except codepolicy.CodePolicyError as error:
        return emit({"status": "error", "error": f"CodePolicyError: {error}"})

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in codepolicy.SAFE_MODULES:
            raise ImportError(f"Import of {name} is not allowed")
        module = __import__(name)
        return types.SimpleNamespace(**{key: getattr(module, key) for key in codepolicy.SAFE_MODULES[name]})

    state = {"index": 0, "pending": None}

    def call(capability, arguments=None):
        try:
            request = {"capability": str(capability), "arguments": json.loads(json.dumps(arguments or {}))}
        except (TypeError, ValueError):
            raise TypeError("Capability arguments must be JSON") from None
        if not isinstance(request["arguments"], dict):
            raise TypeError("Capability arguments must be an object")
        index = state["index"]
        state["index"] += 1
        if index < len(results):
            recorded = results[index]
            if canonical(recorded.get("request")) != canonical(request):
                raise Abort("Tool changed a capability request between runs")
            if "error" in recorded:
                raise ValueError(str(recorded["error"]))
            return copy.deepcopy(recorded.get("result"))
        if index >= MAX_CALLS:
            raise Abort("Too many capability calls")
        state["pending"] = {"request": request, "index": index}
        raise Pending()

    allowed = {name: getattr(builtins, name) for name in codepolicy.SAFE_BUILTINS}
    allowed["__import__"] = safe_import
    allowed["print"] = lambda *args, **kwargs: None
    namespace = {"__builtins__": allowed, "__name__": "tool"}
    try:
        exec(compile(tree, "<tool>", "exec"), namespace)  # noqa: S102 - the policy-checked tree, in a sandbox
        output = namespace["run"](copy.deepcopy(tool_input), call)
    except Pending:
        return emit({"status": "needs_capability", **state["pending"]})
    except Abort as error:
        return emit({"status": "error", "error": str(error)})
    except RecursionError:
        return emit({"status": "error", "error": "RecursionError"})
    except MemoryError:
        return emit({"status": "error", "error": "MemoryError"})
    except Exception as error:
        if state["pending"] is not None:
            # The stop signal was replaced by another error on its way out. Answer the request first.
            return emit({"status": "needs_capability", **state["pending"]})
        return emit({"status": "error", "error": f"{type(error).__name__}: {str(error)[:300]}"})
    if state["pending"] is not None:
        # The tool swallowed the stop signal. The request still has to be answered before a result counts.
        return emit({"status": "needs_capability", **state["pending"]})
    try:
        if not isinstance(output, dict):
            raise TypeError
        output = json.loads(json.dumps(output))
    except (TypeError, ValueError):
        return emit({"status": "error", "error": "Tool output must be a JSON object"})
    emit({"status": "ok", "output": output})


if __name__ == "__main__":
    main()
