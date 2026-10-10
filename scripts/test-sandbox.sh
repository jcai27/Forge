#!/usr/bin/env bash
# Proves the isolation of the real sandbox image and compose service. Uses its own compose project so
# a running development stack is untouched. Requires Docker.
set -uo pipefail
cd "$(dirname "$0")/.."
project=agent-factory-sandbox-test
volume="${project}_sandbox_socket"
failures=0
compose() { docker compose -p "$project" "$@"; }
cleanup() { compose down --volumes --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; failures=$((failures + 1)); }
expect_fail() { # description, command...
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then fail "$name"; else pass "$name"; fi
}
expect_ok() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi
}

cleanup
compose up -d --build sandbox >/dev/null 2>&1 || { echo "FAIL  sandbox service did not start"; exit 1; }
inside() { compose exec -T sandbox "$@"; }
for _ in $(seq 1 40); do inside test -S /run/sandbox/sandbox.sock 2>/dev/null && break; sleep 0.25; done
expect_ok "service listens on the unix socket" inside test -S /run/sandbox/sandbox.sock

# --- the container itself, independent of any in-language policy ---
expect_fail "no route to a public address" inside python -c "import socket; socket.create_connection(('1.1.1.1', 443), timeout=3)"
expect_fail "no DNS" inside python -c "import socket; socket.getaddrinfo('example.com', 443)"
expect_fail "no route to the docker host gateway" inside python -c "import socket; socket.create_connection(('172.17.0.1', 80), timeout=3)"
# Kernels expose inactive tunnel devices in every namespace; what matters is that none but loopback is up.
active=$(inside python -c "
import os
up = []
for name in sorted(os.listdir('/sys/class/net')):
    path = '/sys/class/net/' + name + '/flags'
    if os.path.isfile(path) and int(open(path).read(), 16) & 1:
        up.append(name)
print(','.join(up))" 2>/dev/null)
[ "$active" = "lo" ] && pass "loopback is the only active interface" || fail "loopback is the only active interface (up: $active)"
expect_fail "root filesystem is read-only" inside sh -c "echo x > /app/planted"
expect_fail "cannot write outside tmpfs" inside sh -c "echo x > /etc/planted"
uid=$(inside id -u 2>/dev/null)
[ "$uid" = "10001" ] && pass "runs as an unprivileged user" || fail "runs as an unprivileged user (uid $uid)"
caps=$(inside sh -c "grep CapEff /proc/self/status | awk '{print \$2}'" 2>/dev/null)
[ "$caps" = "0000000000000000" ] && pass "no effective capabilities" || fail "no effective capabilities ($caps)"
nnp=$(inside sh -c "grep NoNewPrivs /proc/self/status | awk '{print \$2}'" 2>/dev/null)
[ "$nnp" = "1" ] && pass "no-new-privileges is set" || fail "no-new-privileges is set ($nnp)"
# Exact allowlist: the base image's own variables and nothing from the application.
unexpected=$(inside env | sed 's/=.*//' | grep -Evx "GPG_KEY|HOME|HOSTNAME|PATH|LANG|PYTHONDONTWRITEBYTECODE|PYTHON_SHA256|PYTHON_VERSION|SANDBOX_WIPE_TMP" | tr '\n' ' ')
[ -z "$unexpected" ] && pass "environment holds only base-image variables" || fail "environment holds only base-image variables (found: $unexpected)"
expect_fail "no docker socket" inside test -e /var/run/docker.sock
expect_fail "application code is absent" inside test -e /app/apps
expect_fail "socket volume is size-limited" inside sh -c "head -c 4000000 /dev/zero > /run/sandbox/fill"
inside rm -f /run/sandbox/fill >/dev/null 2>&1 || true

# --- assume the in-language policy is bypassed: what can arbitrary code in a run still not do? ---
limited() { inside python -I -c "import sys; sys.path.insert(0, '/app'); import runner; runner.apply_limits(); $1"; }
expect_ok "limits apply inside the container" limited "pass"
expect_fail "a run cannot start another process" limited "import os; os.fork()"
expect_fail "a run cannot spawn a shell" limited "import subprocess; subprocess.run(['sh', '-c', 'true'], check=True)"
expect_fail "a run cannot write file content" limited "import os; os.write(os.open('/tmp/planted', os.O_CREAT | os.O_WRONLY), b'x' * 10)"
expect_fail "a run cannot allocate past its memory limit" limited "x = bytearray(900 * 1024 * 1024)"
expect_fail "a run cannot read the service's environment" inside cat /proc/1/environ
expect_fail "a run cannot read the service's memory map" inside cat /proc/1/maps
dumpable=$(inside python -I -c "import sys; sys.path.insert(0, '/app'); import runner, ctypes; runner.apply_limits(); print(ctypes.CDLL(None).prctl(3, 0, 0, 0, 0))" 2>/dev/null)
[ "$dumpable" = "0" ] && pass "a run is not inspectable by a concurrent run" || fail "a run is not inspectable by a concurrent run ($dumpable)"

inside sh -c ': > /tmp/left-by-an-earlier-run; mkdir -p /tmp/left-dir && : > /tmp/left-dir/note' >/dev/null 2>&1

# --- tool runs through the service, from a client that has only the socket ---
client() { # python source on stdin
  docker run --rm -i --network none -v "$volume:/run/sandbox" python:3.13-slim python -
}
result=$(client <<'PY'
import http.client, json, socket

class Unix(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(20)
        self.sock.connect("/run/sandbox/sandbox.sock")

def run(code, tool_input=None, results=()):
    connection = Unix("sandbox")
    body = json.dumps({"code": code, "input": tool_input, "results": list(results)})
    connection.request("POST", "/run", body, {"Content-Type": "application/json"})
    return json.loads(connection.getresponse().read())

def body(lines):
    return "def run(input, call):\n" + "\n".join("    " + line for line in lines) + "\n"

checks = []
def expect(name, outcome, predicate):
    checks.append((name, bool(predicate(outcome)), outcome))

expect("ordinary tool runs", run("import re\n" + body(["return {'ok': bool(re.search('a', input['t']))}"]), {"t": "abc"}),
       lambda o: o == {"status": "ok", "output": {"ok": True}})
expect("capability request is reported, not performed", run(body(["return call('records', {'c': 1})"])),
       lambda o: o["status"] == "needs_capability" and o["request"] == {"capability": "records", "arguments": {"c": 1}})
expect("memory bomb is contained", run(body(["x = 'a' * (2 * 10**9)", "return {'n': len(x)}"])),
       lambda o: o["status"] == "error")
expect("list memory bomb is contained", run(body(["x = [0] * (10**9)", "return {'n': len(x)}"])),
       lambda o: o["status"] == "error")
expect("cpu loop is stopped", run(body(["while True:", "    pass"])), lambda o: o["status"] == "error")
expect("deep recursion is contained", run(body(["def f(n):", "    return f(n + 1)", "return {'x': f(0)}"])),
       lambda o: o["status"] == "error")
expect("imports outside the allowlist are refused", run("import socket\n" + body(["return {}"])),
       lambda o: o["status"] == "error" and "CodePolicyError" in o["error"])
expect("file access is unavailable", run(body(["return {'x': open('/etc/passwd').read()}"])),
       lambda o: o["status"] == "error")
expect("interpreter internals are refused", run(body(["return {'x': str(().__class__.__bases__)}"])),
       lambda o: o["status"] == "error" and "CodePolicyError" in o["error"])
expect("module-level code cannot reach the environment", run("import os\nX = os.environ\n" + body(["return {}"])),
       lambda o: o["status"] == "error" and "CodePolicyError" in o["error"])
expect("oversized output is refused", run(body(["return {'x': 'y' * 400000}"])), lambda o: o["status"] == "error")
print(json.dumps([[name, ok, outcome if not ok else None] for name, ok, outcome in checks]))
PY
)
if [ -z "$result" ]; then
  fail "client could reach the sandbox over the socket"
else
  while IFS=$'\t' read -r ok name detail; do
    [ "$ok" = "True" ] && pass "$name" || fail "$name $detail"
  done < <(python3 -c 'import json,sys
for name, ok, detail in json.loads(sys.argv[1]):
    print(f"{ok}\t{name}\t{json.dumps(detail) if detail else str()}")' "$result")
fi

expect_fail "files left by an earlier run are wiped" inside test -e /tmp/left-by-an-earlier-run
expect_fail "directories left by an earlier run are wiped" inside test -e /tmp/left-dir

# The service must survive the attacks above.
expect_ok "service is still healthy" inside python -c "
import http.client, socket
class U(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX); self.sock.connect('/run/sandbox/sandbox.sock')
c = U('s'); c.request('GET', '/health'); assert c.getresponse().status == 200"

echo
if [ "$failures" -eq 0 ]; then echo "Sandbox isolation: all checks passed"; else echo "Sandbox isolation: $failures check(s) FAILED"; fi
exit "$failures"
