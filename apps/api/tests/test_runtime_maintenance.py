import asyncio

from app.services.runtime_maintenance import RuntimeMaintenanceService


def test_runtime_maintenance_records_manual_cleanup(monkeypatch):
    service = RuntimeMaintenanceService()

    monkeypatch.setattr(
        "app.services.runtime_maintenance.runtime_provisioner.cleanup_expired_workspaces",
        lambda: {"backend": "docker", "cleaned_workspaces": ["ws_demo"], "cleaned_count": 1},
    )
    monkeypatch.setattr(
        "app.services.runtime_maintenance.preview_manager.cleanup_expired_previews",
        lambda: {"backend": "filesystem", "cleaned_previews": ["sub_demo"], "cleaned_count": 1},
    )

    snapshot = asyncio.run(service.run_cleanup(trigger="manual"))

    assert snapshot["trigger"] == "manual"
    assert snapshot["result"]["cleaned_count"] == 2
    assert snapshot["result"]["workspace_cleanup"]["cleaned_workspaces"] == ["ws_demo"]
    assert snapshot["result"]["preview_cleanup"]["cleaned_previews"] == ["sub_demo"]
    status = service.status()
    assert status["last_cleanup"]["result"]["workspace_cleanup"]["cleaned_workspaces"] == ["ws_demo"]
    assert status["cleanup_loop_running"] is False
