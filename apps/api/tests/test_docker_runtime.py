from pathlib import Path

from app.runtime.provisioner import (
    AutoRuntimeProvisioner,
    CommandResult,
    DockerRuntimeProvisioner,
    FilesystemRuntimeProvisioner,
    RuntimePaths,
)


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], CommandResult]):
        self.responses = responses
        self.calls: list[list[str]] = []

    def run(self, args: list[str], cwd: Path | None = None) -> CommandResult:
        self.calls.append(args)
        return self.responses.get(tuple(args), CommandResult(args=args, returncode=0, stdout="", stderr=""))


def make_paths(tmp_path: Path) -> RuntimePaths:
    return RuntimePaths(root=tmp_path / "runtime", templates=tmp_path / "templates")


def test_docker_runtime_builds_and_runs_container(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.runtime.provisioner.which", lambda _: "/usr/local/bin/docker")

    paths = make_paths(tmp_path)
    template = paths.templates / "warehouse-ops-api-v1"
    (template / "app").mkdir(parents=True)
    (template / "app" / "main.py").write_text("print('starter')\n", encoding="utf-8")
    (template / "Dockerfile.runtime").write_text("FROM python:3.13-slim\n", encoding="utf-8")

    responses = {
        ("docker", "version", "--format", "{{.Server.Version}}"): CommandResult(
            args=["docker", "version", "--format", "{{.Server.Version}}"],
            returncode=0,
            stdout="27.0.0\n",
            stderr="",
        ),
        ("docker", "image", "inspect", "local-dev/warehouse-ops-api:v1"): CommandResult(
            args=["docker", "image", "inspect", "local-dev/warehouse-ops-api:v1"],
            returncode=1,
            stdout="",
            stderr="missing",
        ),
        (
            "docker",
            "build",
            "-t",
            "local-dev/warehouse-ops-api:v1",
            "-f",
            str(template / "Dockerfile.runtime"),
            str(template),
        ): CommandResult(
            args=["docker", "build"],
            returncode=0,
            stdout="built\n",
            stderr="",
        ),
        (
            "docker",
            "run",
            "-d",
            "--name",
            "verified-ws-ws_demo",
            "--network",
            "none",
            "--cpus",
            "2",
            "--memory",
            "2g",
            "--pids-limit",
            "256",
            "--security-opt",
            "no-new-privileges",
            "-e",
            "PYTHONPATH=/workspace",
            "-w",
            "/workspace",
            "-v",
            f"{paths.workspaces / 'ws_demo' / 'repo'}:/workspace",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "local-dev/warehouse-ops-api:v1",
            "sleep",
            "infinity",
        ): CommandResult(
            args=["docker", "run"],
            returncode=0,
            stdout="container123\n",
            stderr="",
        ),
        ("docker", "stop", "verified-ws-ws_demo"): CommandResult(
            args=["docker", "stop", "verified-ws-ws_demo"],
            returncode=0,
            stdout="verified-ws-ws_demo\n",
            stderr="",
        ),
        ("docker", "rm", "verified-ws-ws_demo"): CommandResult(
            args=["docker", "rm", "verified-ws-ws_demo"],
            returncode=0,
            stdout="verified-ws-ws_demo\n",
            stderr="",
        ),
    }
    runner = FakeRunner(responses)
    runtime = DockerRuntimeProvisioner(paths, docker_bin="docker", runner=runner)

    summary = runtime.provision_workspace(
        session_id="session_demo",
        workspace_id="ws_demo",
        track_id="track_backend_api_v1",
        starter_repo_ref="local://warehouse-ops-api-v1",
        container_image_ref="local-dev/warehouse-ops-api:v1",
    )
    assert summary["backend"] == "docker"
    assert summary["container_id"] == "container123"
    assert summary["image_status"] == "built"

    artifact = runtime.create_submission_artifact(
        submission_id="sub_demo",
        workspace_id="ws_demo",
        immutable_snapshot={"files": ["app/main.py"]},
    )
    assert artifact["artifact_uri"].startswith("object://")
    assert artifact["artifact_manifest_uri"].startswith("object://")
    assert ("docker", "stop", "verified-ws-ws_demo") in [tuple(call) for call in runner.calls]
    assert ("docker", "rm", "verified-ws-ws_demo") in [tuple(call) for call in runner.calls]


def test_docker_runtime_parses_pytest_results(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.runtime.provisioner.which", lambda _: "/usr/local/bin/docker")
    paths = make_paths(tmp_path)
    template = paths.templates / "warehouse-ops-api-v1"
    (template / "app").mkdir(parents=True)
    (template / "app" / "main.py").write_text("print('starter')\n", encoding="utf-8")
    (template / "Dockerfile.runtime").write_text("FROM python:3.13-slim\n", encoding="utf-8")

    responses = {
        ("docker", "exec", "verified-ws-ws_demo", "sh", "-lc", "pytest -q"): CommandResult(
            args=["docker", "exec"],
            returncode=0,
            stdout="..\n2 passed in 0.10s\n",
            stderr="",
        ),
    }
    runtime = DockerRuntimeProvisioner(paths, docker_bin="docker", runner=FakeRunner(responses))
    (paths.workspaces / "ws_demo" / "repo").mkdir(parents=True)
    (paths.workspaces / "ws_demo" / "metadata").mkdir(parents=True)
    (paths.workspaces / "ws_demo" / "logs").mkdir(parents=True)
    (paths.workspaces / "ws_demo" / "checkpoints").mkdir(parents=True)
    runtime.write_workspace_summary(
        "ws_demo",
        {
            "workspace_id": "ws_demo",
            "backend": "docker",
            "container_name": "verified-ws-ws_demo",
        },
    )

    result = runtime.handle_test_run(workspace_id="ws_demo", payload={"command": "pytest -q"})
    assert result["stdout"] == "..\n2 passed in 0.10s\n"
    assert result["passed_tests"] == 2
    assert result["total_tests"] == 2
    assert result["build_success"] is True


def test_docker_runtime_cleanup_expires_old_workspaces(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.runtime.provisioner.which", lambda _: "/usr/local/bin/docker")
    paths = make_paths(tmp_path)
    responses = {
        ("docker", "stop", "verified-ws-ws_demo"): CommandResult(
            args=["docker", "stop", "verified-ws-ws_demo"],
            returncode=0,
            stdout="verified-ws-ws_demo\n",
            stderr="",
        ),
        ("docker", "rm", "verified-ws-ws_demo"): CommandResult(
            args=["docker", "rm", "verified-ws-ws_demo"],
            returncode=0,
            stdout="verified-ws-ws_demo\n",
            stderr="",
        ),
    }
    runtime = DockerRuntimeProvisioner(paths, docker_bin="docker", runner=FakeRunner(responses))
    workspace_dir = paths.workspaces / "ws_demo" / "metadata"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "workspace.json").write_text(
        __import__("json").dumps(
            {
                "workspace_id": "ws_demo",
                "backend": "docker",
                "container_name": "verified-ws-ws_demo",
                "expires_at": 0,
            }
        ),
        encoding="utf-8",
    )

    result = runtime.cleanup_expired_workspaces()
    assert result["cleaned_workspaces"] == ["ws_demo"]
    assert result["cleaned_count"] == 1


def test_docker_runtime_ignores_empty_workspace_metadata(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.runtime.provisioner.which", lambda _: "/usr/local/bin/docker")
    paths = make_paths(tmp_path)
    runtime = DockerRuntimeProvisioner(paths, docker_bin="docker", runner=FakeRunner({}))

    broken_metadata_dir = paths.workspaces / "ws_broken" / "metadata"
    broken_metadata_dir.mkdir(parents=True)
    (broken_metadata_dir / "workspace.json").write_text("", encoding="utf-8")

    valid_metadata_dir = paths.workspaces / "ws_valid" / "metadata"
    valid_metadata_dir.mkdir(parents=True)
    (valid_metadata_dir / "workspace.json").write_text(
        __import__("json").dumps(
            {
                "workspace_id": "ws_valid",
                "backend": "docker",
                "status": "running",
            }
        ),
        encoding="utf-8",
    )

    status = runtime.runtime_status()
    cleanup = runtime.cleanup_expired_workspaces()

    assert status["workspace_counts"]["total"] == 1
    assert status["workspace_counts"]["by_status"] == {"running": 1}
    assert cleanup["cleaned_count"] == 0


def test_auto_runtime_falls_back_when_docker_unavailable(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.runtime.provisioner.which", lambda _: None)

    paths = make_paths(tmp_path)
    template = paths.templates / "warehouse-ops-api-v1"
    (template / "app").mkdir(parents=True)
    (template / "app" / "main.py").write_text("print('starter')\n", encoding="utf-8")

    docker = DockerRuntimeProvisioner(paths, docker_bin="docker", runner=FakeRunner({}))
    filesystem = FilesystemRuntimeProvisioner(paths)
    runtime = AutoRuntimeProvisioner(preferred=docker, fallback=filesystem)

    summary = runtime.provision_workspace(
        session_id="session_demo",
        workspace_id="ws_demo",
        track_id="track_backend_api_v1",
        starter_repo_ref="local://warehouse-ops-api-v1",
        container_image_ref="local-dev/warehouse-ops-api:v1",
    )
    assert summary["backend"] == "filesystem"


def test_runtime_status_counts_workspace_states(tmp_path: Path):
    paths = make_paths(tmp_path)
    runtime = FilesystemRuntimeProvisioner(paths)
    for workspace_id, status in [("ws_one", "running"), ("ws_two", "expired")]:
        metadata_dir = paths.workspaces / workspace_id / "metadata"
        metadata_dir.mkdir(parents=True)
        (metadata_dir / "workspace.json").write_text(
            __import__("json").dumps(
                {
                    "workspace_id": workspace_id,
                    "backend": "filesystem",
                    "status": status,
                    "created_at": "2026-01-01T09:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

    status = runtime.runtime_status()
    assert status["active_backend"] == "filesystem"
    assert status["workspace_counts"]["total"] == 2
    assert status["workspace_counts"]["by_status"]["running"] == 1
    assert status["workspace_counts"]["by_status"]["expired"] == 1
