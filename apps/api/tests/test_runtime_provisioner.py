from datetime import UTC, datetime
from pathlib import Path

from app.runtime.provisioner import FilesystemRuntimeProvisioner, RuntimePaths


def test_runtime_provisions_workspace_and_submission_artifact(tmp_path: Path):
    provisioner = FilesystemRuntimeProvisioner(
        RuntimePaths(root=tmp_path / "runtime", templates=tmp_path / "templates")
    )

    template = provisioner.paths.templates / "warehouse-ops-api-v1"
    (template / "app").mkdir(parents=True)
    (template / "app" / "main.py").write_text("print('starter')\n", encoding="utf-8")

    workspace = provisioner.provision_workspace(
        session_id="session_demo",
        workspace_id="ws_demo",
        track_id="track_backend_api_v1",
        starter_repo_ref="local://warehouse-ops-api-v1",
        container_image_ref="local-dev/warehouse-ops-api:v1",
    )
    assert workspace["seeded_file_count"] == 1

    event_result = provisioner.append_event(
        workspace_id="ws_demo",
        event_type="checkpoint",
        occurred_at=datetime.now(UTC),
        payload={"label": "checkpoint 1"},
    )
    assert event_result["checkpoint"]["label"] == "checkpoint 1"

    artifact = provisioner.create_submission_artifact(
        submission_id="sub_demo",
        workspace_id="ws_demo",
        immutable_snapshot={"files": ["app/main.py"]},
    )
    assert artifact["artifact_uri"].startswith("object://")
    assert artifact["artifact_manifest_uri"].startswith("object://")
    assert artifact["artifact_sha"]
    assert "workspace_summary" in artifact["immutable_snapshot"]


def test_runtime_supports_file_roundtrip_and_tree(tmp_path: Path):
    provisioner = FilesystemRuntimeProvisioner(
        RuntimePaths(root=tmp_path / "runtime", templates=tmp_path / "templates")
    )

    template = provisioner.paths.templates / "warehouse-ops-api-v1"
    (template / "app").mkdir(parents=True)
    (template / "app" / "main.py").write_text("print('starter')\n", encoding="utf-8")
    (template / "README.md").write_text("# starter\n", encoding="utf-8")

    provisioner.provision_workspace(
        session_id="session_demo",
        workspace_id="ws_demo",
        track_id="track_backend_api_v1",
        starter_repo_ref="local://warehouse-ops-api-v1",
        container_image_ref="local-dev/warehouse-ops-api:v1",
    )

    tree = provisioner.list_workspace_files("ws_demo")
    assert any(item["path"] == "app/main.py" for item in tree)

    write_result = provisioner.write_workspace_file("ws_demo", "app/main.py", "print('updated')\n")
    assert write_result["path"] == "app/main.py"

    file_result = provisioner.read_workspace_file("ws_demo", "app/main.py")
    assert file_result["content"] == "print('updated')\n"


def test_filesystem_runtime_executes_shell_command(tmp_path: Path):
    provisioner = FilesystemRuntimeProvisioner(
        RuntimePaths(root=tmp_path / "runtime", templates=tmp_path / "templates")
    )

    template = provisioner.paths.templates / "warehouse-ops-api-v1"
    (template / "app").mkdir(parents=True)
    (template / "app" / "main.py").write_text("print('starter')\n", encoding="utf-8")

    provisioner.provision_workspace(
        session_id="session_demo",
        workspace_id="ws_demo",
        track_id="track_backend_api_v1",
        starter_repo_ref="local://warehouse-ops-api-v1",
        container_image_ref="local-dev/warehouse-ops-api:v1",
    )

    result = provisioner.handle_terminal_command(workspace_id="ws_demo", command="pwd")
    assert result is not None
    assert result["returncode"] == 0
    assert "ws_demo/repo" in result["stdout"]
