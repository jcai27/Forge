from pathlib import Path

from app.api.preview import _rewrite_location
from app.runtime.preview import DockerPreviewManager, FilesystemPreviewManager
from app.runtime.provisioner import CommandResult, RuntimePaths


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], CommandResult]):
        self.responses = responses
        self.calls: list[list[str]] = []

    def run(self, args: list[str], cwd: Path | None = None) -> CommandResult:
        self.calls.append(args)
        return self.responses.get(tuple(args), CommandResult(args=args, returncode=0, stdout="", stderr=""))


def test_filesystem_preview_serves_http_response(tmp_path: Path):
    manager = FilesystemPreviewManager(RuntimePaths(root=tmp_path / "runtime", templates=tmp_path / "templates"))
    handle = manager.live_handle(session_id="session_demo", workspace_id="ws_demo")
    handle.repo_root.mkdir(parents=True, exist_ok=True)
    (handle.repo_root / "index.html").write_text("preview-ok", encoding="utf-8")
    manager.allocate_port = lambda: 41001
    manager._probe_readiness = lambda summary: True
    manager._proxy_http_request = lambda **kwargs: {
        "status_code": 200,
        "headers": {"Content-Type": "text/plain"},
        "content": b"preview-ok",
    }

    summary = manager.start(
        handle,
        {
            "enabled": True,
            "mode": "http",
            "start_command_template": "python -c \"import time; time.sleep(10)\"",
            "readiness_path": "/",
            "default_path": "/",
            "startup_timeout_seconds": 5,
        },
    )
    assert summary["status"] == "ready"

    proxy_result = manager.proxy_request(
        handle,
        summary,
        method="GET",
        request_path="/",
        query_string="",
        headers={},
        body=b"",
    )
    assert proxy_result["status_code"] == 200
    assert b"preview-ok" in proxy_result["content"]

    stopped = manager.stop(handle)
    assert stopped["status"] == "stopped"


def test_docker_preview_publishes_loopback_port(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.runtime.preview.which", lambda _: "/usr/local/bin/docker")
    paths = RuntimePaths(root=tmp_path / "runtime", templates=tmp_path / "templates")
    handle_repo = paths.workspaces / "ws_demo" / "repo"
    handle_repo.mkdir(parents=True, exist_ok=True)

    runner = FakeRunner(
        {
            (
                "docker",
                "run",
                "-d",
                "--name",
                "verified-preview-live-ws_demo",
                "--cpus",
                "2",
                "--memory",
                "2g",
                "--pids-limit",
                "256",
                "--security-opt",
                "no-new-privileges",
                "--cap-drop",
                "ALL",
                "--read-only",
                "-p",
                "127.0.0.1:41001:41001",
                "-e",
                "PYTHONPATH=/workspace",
                "-w",
                "/workspace",
                "-v",
                f"{handle_repo}:/workspace",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                "local-dev/warehouse-ops-api:v1",
                "sh",
                "-lc",
                "uvicorn app.main:app --host 0.0.0.0 --port 41001",
            ): CommandResult(args=["docker", "run"], returncode=0, stdout="container-preview\n", stderr=""),
        }
    )
    manager = DockerPreviewManager(paths, docker_bin="docker", runner=runner)
    monkeypatch.setattr(manager, "allocate_port", lambda: 41001)
    monkeypatch.setattr(manager, "_probe_readiness", lambda summary: True)
    monkeypatch.setattr(manager, "_process_terminated", lambda summary: False)

    handle = manager.live_handle(session_id="session_demo", workspace_id="ws_demo")
    summary = manager.start(
        handle,
        {
            "enabled": True,
            "mode": "http",
            "start_command_template": "uvicorn app.main:app --host 0.0.0.0 --port {PORT}",
            "readiness_path": "/health",
            "default_path": "/docs",
            "startup_timeout_seconds": 2,
        },
        image_ref="local-dev/warehouse-ops-api:v1",
    )

    assert summary["status"] == "ready"
    assert any(call[0:5] == ["docker", "run", "-d", "--name", "verified-preview-live-ws_demo"] for call in runner.calls)
    assert any("-p" in call and "127.0.0.1:41001:41001" in call for call in runner.calls)


def test_preview_proxy_rewrites_local_redirect():
    rewritten = _rewrite_location(
        "http://127.0.0.1:41001/docs",
        "/api/preview/live/session_demo",
        "http://127.0.0.1:41001",
    )
    assert rewritten == "/api/preview/live/session_demo/docs"


def test_preview_get_keeps_starting_state_without_process_handle(tmp_path: Path):
    manager = FilesystemPreviewManager(RuntimePaths(root=tmp_path / "runtime", templates=tmp_path / "templates"))
    handle = manager.live_handle(session_id="session_demo", workspace_id="ws_demo")
    handle.repo_root.mkdir(parents=True, exist_ok=True)
    manager.write_summary(
        handle,
        {
            "scope": "live",
            "subject_id": "session_demo",
            "runtime_id": "ws_demo",
            "status": "starting",
            "backend": "filesystem",
            "port": 41001,
            "local_url": "http://127.0.0.1:41001",
            "readiness_path": "/health",
            "default_path": "/docs",
        },
    )

    summary = manager.get(handle)

    assert summary["status"] == "starting"
    assert summary.get("error") is None
