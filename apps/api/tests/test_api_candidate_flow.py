import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.runtime.preview import preview_manager
from app.runtime.provisioner import runtime_provisioner
from app.services.auth import _totp_code


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _csrf_headers(client: TestClient) -> dict[str, str]:
    csrf = client.cookies.get(settings.auth_csrf_cookie_name)
    return {"x-csrf-token": csrf} if csrf else {}


def _login(client: TestClient, email: str, password: str = "demo-password") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()


def _enable_internal_mfa(client: TestClient) -> None:
    enroll = client.post("/api/auth/mfa/enroll", headers=_csrf_headers(client))
    assert enroll.status_code == 200
    secret = enroll.json()["enrollment"]["secret"]
    verify = client.post("/api/auth/mfa/verify", json={"code": _totp_code(secret, int(time.time()) // 30)}, headers=_csrf_headers(client))
    assert verify.status_code == 200


def test_candidate_api_flow_launches_preview_and_submits(monkeypatch):
    workspace_summaries: dict[str, dict] = {}
    preview_summaries: dict[str, dict] = {}

    monkeypatch.setattr(settings, "runtime_cleanup_on_startup", False)
    monkeypatch.setattr(settings, "runtime_cleanup_interval_seconds", 0)
    monkeypatch.setattr(settings, "runtime_worker_poll_interval_seconds", 0.05)
    monkeypatch.setattr(settings, "runtime_worker_embed_in_api", True)

    def fake_provision_workspace(*, session_id: str, workspace_id: str, track_id: str, starter_repo_ref: str, container_image_ref: str):
        summary = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "track_id": track_id,
            "backend": "docker",
            "status": "running",
            "repo_root": f"/tmp/{workspace_id}/repo",
            "seeded_file_count": 3,
            "seeded_files": ["app/main.py", "app/routes.py", "tests/test_inventory.py"],
            "container_image_ref": container_image_ref,
            "created_at": _utc_iso(),
            "container_name": f"verified-ws-{workspace_id}",
            "container_id": f"container-{workspace_id}",
        }
        workspace_summaries[workspace_id] = summary
        return summary

    def fake_workspace_summary(workspace_id: str):
        return workspace_summaries.get(workspace_id)

    def fake_create_submission_artifact(*, submission_id: str, workspace_id: str, immutable_snapshot: dict):
        return {
            "artifact_uri": f"object://submissions/{submission_id}/repo",
            "artifact_sha": f"sha-{submission_id}",
            "build_log_uri": f"object://submissions/{submission_id}/logs/build.log",
            "test_log_uri": f"object://submissions/{submission_id}/logs/tests.log",
            "artifact_manifest_uri": f"object://submissions/{submission_id}/manifest.json",
            "immutable_snapshot": {
                **immutable_snapshot,
                "evidence_uris": {
                    "events": f"object://submissions/{submission_id}/events.jsonl",
                    "commands": f"object://submissions/{submission_id}/logs/commands.log",
                },
            },
        }

    def fake_preview_start(handle, preview_config: dict, *, image_ref: str | None = None):
        summary = {
            "scope": handle.scope,
            "subject_id": handle.subject_id,
            "runtime_id": handle.runtime_id,
            "status": "ready",
            "backend": "docker",
            "repo_root": str(handle.repo_root),
            "host": "127.0.0.1",
            "port": 41099,
            "local_url": "http://127.0.0.1:41099",
            "readiness_path": "/health",
            "default_path": "/docs",
            "started_at": _utc_iso(),
            "last_accessed_at": _utc_iso(),
            "last_ready_at": _utc_iso(),
            "stopped_at": None,
            "error": None,
            "log_path": str(handle.log_path),
            "container_name": f"verified-preview-{handle.runtime_id}",
            "container_id": f"preview-{handle.runtime_id}",
            "image_ref": image_ref,
        }
        preview_summaries[handle.runtime_id] = summary
        return summary

    def fake_preview_stop(handle):
        existing = preview_summaries.get(handle.runtime_id, {})
        summary = {
            **existing,
            "scope": handle.scope,
            "subject_id": handle.subject_id,
            "runtime_id": handle.runtime_id,
            "status": "stopped",
            "backend": existing.get("backend", "docker"),
            "repo_root": existing.get("repo_root", str(handle.repo_root)),
            "host": existing.get("host", "127.0.0.1"),
            "port": existing.get("port", 41099),
            "local_url": existing.get("local_url", "http://127.0.0.1:41099"),
            "readiness_path": existing.get("readiness_path", "/health"),
            "default_path": existing.get("default_path", "/docs"),
            "started_at": existing.get("started_at", _utc_iso()),
            "last_accessed_at": _utc_iso(),
            "last_ready_at": existing.get("last_ready_at"),
            "stopped_at": _utc_iso(),
            "error": None,
            "log_path": str(handle.log_path),
            "container_name": existing.get("container_name"),
            "container_id": existing.get("container_id"),
            "image_ref": existing.get("image_ref"),
        }
        preview_summaries[handle.runtime_id] = summary
        return summary

    monkeypatch.setattr(runtime_provisioner, "provision_workspace", fake_provision_workspace)
    monkeypatch.setattr(runtime_provisioner, "workspace_summary", fake_workspace_summary)
    monkeypatch.setattr(runtime_provisioner, "create_submission_artifact", fake_create_submission_artifact)
    monkeypatch.setattr(preview_manager, "start", fake_preview_start)
    monkeypatch.setattr(preview_manager, "stop", fake_preview_stop)

    with TestClient(app) as client:
        _login(client, "reviewer@verified.dev")
        _enable_internal_mfa(client)
        attempt = client.post(
            "/api/internal/attempts",
            json={
                "user_id": "candidate_demo",
                "track_version_id": "track_backend_api_v1",
                "organization_id": "org_design_partner_demo",
                "candidate_label": "Integration Flow",
            },
            headers=_csrf_headers(client),
        ).json()["attempt"]

        client.post("/api/auth/logout", headers=_csrf_headers(client))
        _login(client, "candidate@example.com")

        launched = client.post("/api/candidate/sessions", json={"attempt_id": attempt["id"]}, headers=_csrf_headers(client)).json()
        session_id = launched["session"]["id"]

        session = launched["session"]
        for _ in range(80):
            session = client.get(f"/api/candidate/sessions/{session_id}").json()["session"]
            if session["status"] == "ready":
                break
            time.sleep(0.05)
        assert session["status"] == "ready"
        assert session["latest_runtime_job"]["job_type"] == "provision_workspace"
        assert session["latest_runtime_job"]["status"] == "succeeded"

        preview_start = client.post(f"/api/candidate/sessions/{session_id}/preview/start", headers=_csrf_headers(client)).json()
        assert preview_start["preview"]["status"] == "starting"
        assert preview_start["session"]["latest_runtime_job"]["job_type"] == "start_preview"

        session = preview_start["session"]
        for _ in range(80):
            session = client.get(f"/api/candidate/sessions/{session_id}").json()["session"]
            if (session.get("preview_summary") or {}).get("status") == "ready":
                break
            time.sleep(0.05)
        assert session["preview_summary"]["status"] == "ready"
        assert session["latest_runtime_job"]["status"] == "succeeded"

        queued_submission = client.post(
            "/api/candidate/submissions",
            json={
                "session_id": session_id,
                "visibility": "private",
                "candidate_summary_note": "Implemented safer inventory adjustment writes.",
                "tradeoff_note": "Prioritized correctness and tests before broader reporting polish.",
                "unfinished_work_note": "Would add richer audit visibility next.",
                "submission_checklist": {
                    "brief_reviewed": True,
                    "checks_run": True,
                    "preview_current": True,
                    "reflection_ready": True,
                },
            },
            headers=_csrf_headers(client),
        ).json()
        report_id = queued_submission["report"]["id"]
        assert queued_submission["session"]["status"] == "submitting"
        assert queued_submission["session"]["latest_runtime_job"]["job_type"] == "freeze_submission"

        session = queued_submission["session"]
        for _ in range(120):
            session = client.get(f"/api/candidate/sessions/{session_id}").json()["session"]
            if session["status"] == "submitted":
                break
            time.sleep(0.05)
        assert session["status"] == "submitted"
        assert session["latest_runtime_job"]["status"] == "succeeded"

        report = client.get(f"/api/candidate/reports/{report_id}").json()["report"]
        for _ in range(40):
            review_status = report["candidate_summary"]["review_status"]["publication_state"]
            if review_status != "finalizing_submission":
                break
            time.sleep(0.05)
            report = client.get(f"/api/candidate/reports/{report_id}").json()["report"]

        assert report["candidate_summary"]["review_status"]["publication_state"] == "awaiting_review"
        assert report["candidate_summary"]["submission"]["artifact_uri"].startswith("object://")
        assert report["candidate_summary"]["candidate_reflection"]["tradeoff_note"] == "Prioritized correctness and tests before broader reporting polish."
        assert report["employer_summary"]["candidate_reflection"]["unfinished_work_note"] == "Would add richer audit visibility next."


def test_internal_attempts_accepts_cors_preflight_from_local_web_port():
    with TestClient(app) as client:
        response = client.options(
            "/api/internal/attempts",
            headers={
                "Origin": "http://localhost:3100",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3100"
