"""Sandbox service: accepts tool runs on a Unix socket and executes each in a fresh, limited process.

Run this only inside the sandbox container (no network, read-only root, dropped capabilities). The
service never opens an outbound connection and holds no credentials. Standard library only.
"""

import json
import os
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler

MAX_BODY = 4_000_000
MAX_STDOUT = 1_000_000
WALL_SECONDS = 5
HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "runner.py")
POLICY_DIR = os.environ.get("SANDBOX_POLICY_DIR", HERE)
slots = threading.BoundedSemaphore(4)
# In the container the whole temp filesystem belongs to this service and is wiped between runs. Anywhere
# else only this service's own private directory is touched.
WIPE_ALL = os.environ.get("SANDBOX_WIPE_TMP") == "1"
BASE = tempfile.gettempdir() if WIPE_ALL else tempfile.mkdtemp(prefix="sandbox-runs-")
active, active_lock = set(), threading.Lock()


def wipe_leftovers():
    """Remove anything a finished run left behind, so one run cannot leave a message for the next."""
    with active_lock:
        keep = set(active)
        try:
            entries = os.listdir(BASE)
        except OSError:
            return
        for entry in entries:
            if entry in keep:
                continue
            path = os.path.join(BASE, entry)
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.unlink(path)
            except OSError:
                pass


def run_tool(body):
    workdir = tempfile.mkdtemp(prefix="run-", dir=BASE)
    with active_lock:
        active.add(os.path.basename(workdir))
    try:
        return execute(body, workdir)
    finally:
        with active_lock:
            active.discard(os.path.basename(workdir))
        wipe_leftovers()


def execute(body, workdir):
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-I", "-S", "-B", RUNNER, POLICY_DIR],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=workdir,
            env={},
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        return {"status": "error", "error": "Sandbox could not start a run"}
    try:
        stdout, _ = process.communicate(body, timeout=WALL_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return {"status": "error", "error": "Tool exceeded the time limit"}
    finally:
        # Nothing a run started may outlive it. The run has its own session, so this reaches all of it.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    if len(stdout) > MAX_STDOUT:
        return {"status": "error", "error": "Tool output exceeds the size limit"}
    try:
        result = json.loads(stdout)
        if not isinstance(result, dict) or result.get("status") not in ("ok", "needs_capability", "error"):
            raise ValueError
        return result
    except ValueError:
        # Killed by a resource limit or crashed before reporting.
        return {"status": "error", "error": "Tool run ended without a result"}


class Handler(BaseHTTPRequestHandler):
    server_version = "sandbox"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        return

    def address_string(self):
        return "unix"

    def reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"ok": True})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            return self.reply(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.reply(411, {"error": "length required"})
        if length < 0 or length > MAX_BODY:
            return self.reply(413, {"error": "request too large"})
        body = self.rfile.read(length)
        if not slots.acquire(blocking=False):
            return self.reply(429, {"error": "sandbox busy"})
        try:
            self.reply(200, run_tool(body))
        finally:
            slots.release()


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def no_inspection():
    """A tool run shares this service's user. Non-dumpable means it cannot ptrace or read this process."""
    try:
        import ctypes

        ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE = 4
    except (OSError, AttributeError):
        pass  # not Linux: the container that provides isolation is Linux


def main():
    no_inspection()
    path = sys.argv[1]
    if os.path.exists(path):
        os.unlink(path)
    server = Server(path, Handler)
    os.chmod(path, 0o666)
    server.serve_forever()


if __name__ == "__main__":
    main()
