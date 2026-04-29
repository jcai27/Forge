from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.db.models import ReportAccess, ReportAccessStatus, Session as CandidateSession, SessionStatus
from app.db.session import SessionLocal
from app.runtime.preview import preview_manager
from app.runtime.provisioner import runtime_provisioner

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def expire_stale_sessions() -> dict[str, Any]:
    db = SessionLocal()
    try:
        now = utcnow()
        sessions = (
            db.query(CandidateSession)
            .filter(CandidateSession.status.in_([SessionStatus.ready.value, SessionStatus.active.value, SessionStatus.provisioning.value]))
            .all()
        )
        expired: list[str] = []
        for session in sessions:
            last_seen = session.heartbeat_at or session.last_activity_at or session.started_at
            if not last_seen:
                continue
            idle_seconds = max((now - last_seen.replace(tzinfo=UTC) if last_seen.tzinfo is None else now - last_seen).total_seconds(), 0)
            if idle_seconds < settings.runtime_session_timeout_seconds:
                continue
            session.status = SessionStatus.expired.value
            session.ended_at = now
            session.runtime_failure_reason = "Session expired due to inactivity"
            db.add(session)
            expired.append(session.id)
        db.commit()
        return {"expired_sessions": expired, "expired_count": len(expired)}
    finally:
        db.close()


def expire_report_access() -> dict[str, Any]:
    db = SessionLocal()
    try:
        now = utcnow()
        accesses = db.query(ReportAccess).filter(ReportAccess.status == ReportAccessStatus.active.value).all()
        expired: list[str] = []
        for access in accesses:
            if not access.expires_at or access.expires_at > now:
                continue
            access.status = ReportAccessStatus.expired.value
            db.add(access)
            expired.append(access.id)
        db.commit()
        return {"expired_accesses": expired, "expired_count": len(expired)}
    finally:
        db.close()


def execute_cleanup_pass() -> dict[str, Any]:
    workspace_result = runtime_provisioner.cleanup_expired_workspaces()
    preview_result = preview_manager.cleanup_expired_previews()
    session_result = expire_stale_sessions()
    access_result = expire_report_access()
    return {
        "workspace_cleanup": workspace_result,
        "preview_cleanup": preview_result,
        "session_cleanup": session_result,
        "access_cleanup": access_result,
        "cleaned_count": (
            workspace_result.get("cleaned_count", 0)
            + preview_result.get("cleaned_count", 0)
            + session_result.get("expired_count", 0)
            + access_result.get("expired_count", 0)
        ),
    }


class RuntimeMaintenanceService:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._last_cleanup: dict[str, Any] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if settings.runtime_cleanup_on_startup:
            await self.run_cleanup(trigger="startup")

        if settings.runtime_cleanup_interval_seconds > 0:
            self._task = asyncio.create_task(self._run_loop(), name="runtime-cleanup-loop")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(settings.runtime_cleanup_interval_seconds)
            await self.run_cleanup(trigger="interval")

    async def run_cleanup(self, *, trigger: str) -> dict[str, Any]:
        started_at = utcnow().isoformat()
        try:
            result = await asyncio.to_thread(execute_cleanup_pass)
            snapshot = {
                "trigger": trigger,
                "started_at": started_at,
                "completed_at": utcnow().isoformat(),
                "result": result,
                "error": None,
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Runtime cleanup failed")
            snapshot = {
                "trigger": trigger,
                "started_at": started_at,
                "completed_at": utcnow().isoformat(),
                "result": None,
                "error": str(exc),
            }
        self._last_cleanup = snapshot
        return snapshot

    def status(self) -> dict[str, Any]:
        return {
            "cleanup_on_startup": settings.runtime_cleanup_on_startup,
            "cleanup_interval_seconds": settings.runtime_cleanup_interval_seconds,
            "cleanup_loop_running": self._task is not None and not self._task.done(),
            "last_cleanup": self._last_cleanup,
        }


runtime_maintenance = RuntimeMaintenanceService()
