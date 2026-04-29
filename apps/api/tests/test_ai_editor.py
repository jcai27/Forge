import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import app
from app.runtime.provisioner import runtime_provisioner
from app.services import ai_editor


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def test_candidate_workspace_assistant_applies_model_changes(monkeypatch):
    workspace_summaries: dict[str, dict] = {}
    workspace_files: dict[str, dict[str, str]] = {}
    updated_at_by_path: dict[tuple[str, str], str] = {}

    def file_payload(workspace_id: str, path: str) -> dict[str, str | int]:
        content = workspace_files[workspace_id][path]
        return {
            "path": path,
            "content": content,
            "size": len(content),
            "updated_at": updated_at_by_path[(workspace_id, path)],
        }

    def fake_provision_workspace(*, session_id: str, workspace_id: str, track_id: str, starter_repo_ref: str, container_image_ref: str):
        workspace_files[workspace_id] = {
            "app/routes.py": "def adjust_inventory(quantity: int) -> int:\n    return quantity\n",
            "README.md": "# Warehouse Ops API\n",
        }
        for path in workspace_files[workspace_id]:
            updated_at_by_path[(workspace_id, path)] = _utc_iso()
        summary = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "track_id": track_id,
            "backend": "docker",
            "status": "running",
            "repo_root": f"/tmp/{workspace_id}/repo",
            "seeded_file_count": len(workspace_files[workspace_id]),
            "seeded_files": list(workspace_files[workspace_id]),
            "container_image_ref": container_image_ref,
            "created_at": _utc_iso(),
            "container_name": f"verified-ws-{workspace_id}",
            "container_id": f"container-{workspace_id}",
        }
        workspace_summaries[workspace_id] = summary
        return summary

    def fake_workspace_summary(workspace_id: str):
        return workspace_summaries.get(workspace_id)

    def fake_append_event(*, workspace_id: str, event_type: str, occurred_at: datetime, payload: dict):
        return {
            "event_log_path": f"/tmp/{workspace_id}/events.jsonl",
            "checkpoint": None,
            "command_result": None,
            "test_result": None,
        }

    def fake_list_workspace_files(workspace_id: str):
        return [
            {
                "path": path,
                "name": path.rsplit("/", 1)[-1],
                "type": "file",
                "size": len(content),
            }
            for path, content in sorted(workspace_files[workspace_id].items())
        ]

    def fake_read_workspace_file(workspace_id: str, path: str):
        return file_payload(workspace_id, path)

    def fake_write_workspace_file(workspace_id: str, path: str, content: str, expected_updated_at: str | None = None):
        workspace_files[workspace_id][path] = content
        updated_at_by_path[(workspace_id, path)] = _utc_iso()
        return file_payload(workspace_id, path)

    def fake_call_openai_workspace_editor(**kwargs):
        assert kwargs["selected_path"] == "app/routes.py"
        return {
            "summary": "Added defensive inventory handling and an assertion note in the README.",
            "changes": [
                {
                    "path": "app/routes.py",
                    "content": "def adjust_inventory(quantity: int) -> int:\n    return max(quantity, 0)\n",
                    "summary": "Clamp negative inventory adjustments.",
                },
                {
                    "path": "README.md",
                    "content": "# Warehouse Ops API\n\nInventory adjustments now clamp at zero.\n",
                    "summary": "Document the new guardrail.",
                },
            ],
            "suggested_command": "pytest -q",
            "follow_up": "Add a regression test for a negative adjustment request.",
        }

    monkeypatch.setattr(runtime_provisioner, "provision_workspace", fake_provision_workspace)
    monkeypatch.setattr(runtime_provisioner, "workspace_summary", fake_workspace_summary)
    monkeypatch.setattr(runtime_provisioner, "append_event", fake_append_event)
    monkeypatch.setattr(runtime_provisioner, "list_workspace_files", fake_list_workspace_files)
    monkeypatch.setattr(runtime_provisioner, "read_workspace_file", fake_read_workspace_file)
    monkeypatch.setattr(runtime_provisioner, "write_workspace_file", fake_write_workspace_file)
    monkeypatch.setattr(ai_editor, "_call_openai_workspace_editor", fake_call_openai_workspace_editor)

    with TestClient(app) as client:
        launched = client.post(
            "/api/candidate/sessions",
            json={"track_version_id": "track_backend_api_v1"},
            headers={"X-Forge-Dev-Auth": "candidate"},
        ).json()

        session_id = launched["session"]["id"]
        session = launched["session"]
        for _ in range(80):
            session = client.get(
                f"/api/candidate/sessions/{session_id}",
                headers={"X-Forge-Dev-Auth": "candidate"},
            ).json()["session"]
            if session["status"] == "ready":
                break
            time.sleep(0.05)

        assert session["status"] == "ready"

        response = client.post(
            f"/api/candidate/sessions/{session_id}/assistant",
            json={
                "prompt": "Clamp negative inventory values and update the readme.",
                "selected_path": "app/routes.py",
                "open_paths": ["app/routes.py", "README.md"],
            },
            headers={"X-Forge-Dev-Auth": "candidate"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["assistant"]["summary"] == "Added defensive inventory handling and an assertion note in the README."
        assert payload["assistant"]["suggested_command"] == "pytest -q"
        assert payload["assistant"]["follow_up"] == "Add a regression test for a negative adjustment request."
        assert [item["path"] for item in payload["assistant"]["changed_files"]] == ["app/routes.py", "README.md"]
        assert payload["assistant"]["changed_files"][0]["content"] == "def adjust_inventory(quantity: int) -> int:\n    return max(quantity, 0)\n"

        reloaded = client.get(
            f"/api/candidate/sessions/{session_id}/workspace/file?path=app/routes.py",
            headers={"X-Forge-Dev-Auth": "candidate"},
        ).json()
        assert reloaded["file"]["content"] == "def adjust_inventory(quantity: int) -> int:\n    return max(quantity, 0)\n"
