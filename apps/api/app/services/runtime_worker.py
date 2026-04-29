from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import suppress
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import runtime_worker_embeds_in_api, settings
from app.db.models import (
    AttemptStatus,
    EscalationState,
    Report,
    ReportStatus,
    ReviewState,
    RuntimeJob,
    RuntimeJobStatus,
    Session as CandidateSession,
    SessionEvent,
    SessionStatus,
    Submission,
    TrackVersion,
)
from app.db.session import SessionLocal
from app.runtime.preview import PreviewUnavailableError, preview_manager
from app.runtime.provisioner import DockerUnavailableError, runtime_provisioner
from app.schemas import SessionEventCreate
from app.services.platform import (
    _default_preview_summary,
    build_candidate_summary,
    build_employer_summary,
    calculate_benchmark_summary,
    get_attempt_or_404,
    get_report_or_404,
    get_session_or_404,
    get_submission_or_404,
    preview_config_for_track,
    preview_enabled_for_track,
    summarize_automated_score,
    summarize_events,
    summarize_integrity,
    summarize_provenance,
    utcnow,
    with_proxy_urls,
)
from app.services.runtime_control import create_runtime_job, log_audit_event, mark_job_failed, mark_job_succeeded
from app.services.runtime_maintenance import execute_cleanup_pass

logger = logging.getLogger(__name__)


def claim_next_runtime_job(db: Session) -> RuntimeJob | None:
    now = utcnow()
    query = (
        select(RuntimeJob)
        .where(
            RuntimeJob.status == RuntimeJobStatus.queued.value,
            or_(RuntimeJob.available_at.is_(None), RuntimeJob.available_at <= now),
        )
        .order_by(RuntimeJob.scheduled_at.asc(), RuntimeJob.created_at.asc())
        .limit(1)
    )
    if db.bind and db.bind.dialect.name != "sqlite":
        query = query.with_for_update(skip_locked=True)
    candidate = db.execute(query).scalar_one_or_none()
    if not candidate:
        return None

    candidate.status = RuntimeJobStatus.running.value
    candidate.started_at = now
    candidate.completed_at = None
    candidate.error_text = None
    candidate.attempts_count = (candidate.attempts_count or 0) + 1
    candidate.heartbeat_at = now
    candidate.lease_expires_at = now + timedelta(seconds=settings.runtime_job_lease_seconds)
    db.add(candidate)
    db.commit()
    return db.query(RuntimeJob).filter(RuntimeJob.id == candidate.id).first()


def _pending_candidate_summary(track: TrackVersion, session: CandidateSession, submission: Submission) -> dict[str, Any]:
    return {
        "track": {
            "id": track.id,
            "title": track.title,
            "version": track.version,
            "duration_minutes": track.duration_minutes,
            "content_metadata": track.content_metadata_json,
        },
        "submission": {
            "id": submission.id,
            "status": "finalizing",
            "automated_score": {"total_score": 0, "correctness_score": 0, "quality_score": 0},
            "benchmark_summary": {"overall_percentile": None, "cohort_size": 0, "benchmark_state": "pending"},
        },
        "workspace": runtime_provisioner.workspace_summary(session.workspace_id),
        "preview": session.preview_summary_json,
        "timeline_summary": {
            "work_pattern_summary": "Submission is finalizing. Artifact freezing and evidence assembly are still running.",
            "integrity": {
                "flags": [],
                "review_signals": [],
                "confidence_score": 100,
                "ai_usage_summary": "Pending final evidence assembly.",
            },
            "timeline": [],
        },
        "review_status": {
            "state": ReviewState.pending_review.value,
            "portable": False,
            "publication_state": "finalizing_submission",
        },
        "next_steps": [
            "The submitted artifact is being frozen.",
            "A reviewer queue entry will be created once finalization completes.",
        ],
    }


def _pending_employer_summary(track: TrackVersion, session: CandidateSession) -> dict[str, Any]:
    return {
        "track": {
            "id": track.id,
            "title": track.title,
            "version": track.version,
            "role_family": track.role_family,
            "content_metadata": track.content_metadata_json,
        },
        "artifact_summary": {
            "workspace_id": session.workspace_id,
            "artifact_uri": None,
            "artifact_sha": None,
            "artifact_manifest_uri": None,
            "workspace": runtime_provisioner.workspace_summary(session.workspace_id),
        },
        "dimension_breakdown": [],
        "integrity_summary": {
            "confidence_score": 100,
            "flags": [],
            "review_signals": [],
            "ai_usage_summary": "Pending final evidence assembly.",
        },
        "benchmark_summary": {"overall_percentile": None, "cohort_size": 0, "benchmark_state": "pending"},
        "preview_available": False,
        "preview_access_token": None,
        "preview_default_path": None,
        "recommended_question": "Await finalized submission evidence before using this report.",
    }


def enqueue_cleanup_job(db: Session, *, trigger: str) -> RuntimeJob:
    job = create_runtime_job(
        db,
        job_type="cleanup_runtime",
        target_type="runtime",
        target_id="global",
        payload={"trigger": trigger},
    )
    db.commit()
    db.refresh(job)
    return job


class RuntimeJobWorkerService:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._last_result: dict[str, Any] | None = None

    async def start(self) -> None:
        if not settings.runtime_worker_enabled:
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="runtime-job-worker")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while True:
            processed = await self.run_once()
            if processed == 0:
                await asyncio.sleep(settings.runtime_worker_poll_interval_seconds)

    async def run_once(self) -> int:
        processed = 0
        for _ in range(max(settings.runtime_worker_batch_size, 1)):
            ran = await asyncio.to_thread(self._run_single_job)
            if not ran:
                break
            processed += 1
        return processed

    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.runtime_worker_enabled,
            "embedded": runtime_worker_embeds_in_api(),
            "poll_interval_seconds": settings.runtime_worker_poll_interval_seconds,
            "batch_size": settings.runtime_worker_batch_size,
            "lease_seconds": settings.runtime_job_lease_seconds,
            "loop_running": self._task is not None and not self._task.done(),
            "last_result": self._last_result,
        }

    def _run_single_job(self) -> bool:
        db = SessionLocal()
        try:
            job = claim_next_runtime_job(db)
            if not job:
                return False
            try:
                job.heartbeat_at = utcnow()
                job.lease_expires_at = utcnow() + timedelta(seconds=settings.runtime_job_lease_seconds)
                db.add(job)
                db.commit()
                result = self._dispatch_job(db, job)
                self._last_result = {"job_id": job.id, "job_type": job.job_type, "status": "succeeded"}
                logger.info("Processed runtime job %s (%s)", job.id, job.job_type)
                return True
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Runtime job %s failed", job.id)
                job = db.query(RuntimeJob).filter(RuntimeJob.id == job.id).first()
                if job:
                    mark_job_failed(db, job, str(exc))
                    db.commit()
                self._last_result = {"job_id": job.id if job else None, "job_type": job.job_type if job else None, "status": "failed", "error": str(exc)}
                return True
        finally:
            db.close()

    def _dispatch_job(self, db: Session, job: RuntimeJob) -> dict[str, Any]:
        if job.job_type == "provision_workspace":
            return self._process_provision_workspace(db, job)
        if job.job_type == "start_preview":
            return self._process_start_preview(db, job)
        if job.job_type == "stop_preview":
            return self._process_stop_preview(db, job)
        if job.job_type == "freeze_submission":
            return self._process_freeze_submission(db, job)
        if job.job_type == "cleanup_runtime":
            return self._process_cleanup(db, job)
        raise RuntimeError(f"Unsupported runtime job type: {job.job_type}")

    def _process_provision_workspace(self, db: Session, job: RuntimeJob) -> dict[str, Any]:
        session = get_session_or_404(db, job.target_id)
        track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
        if not track:
            raise RuntimeError("Track version not found")

        session.status = SessionStatus.provisioning.value
        session.environment_summary_json = {
            **(session.environment_summary_json or {}),
            "readiness": "provisioning",
            "track_content": track.content_metadata_json,
        }
        db.add(session)
        db.commit()

        try:
            workspace_summary = runtime_provisioner.provision_workspace(
                session_id=session.id,
                workspace_id=session.workspace_id,
                track_id=track.id,
                starter_repo_ref=track.starter_repo_ref,
                container_image_ref=track.container_image_ref,
            )
        except DockerUnavailableError as exc:
            session = get_session_or_404(db, session.id)
            session.status = SessionStatus.runtime_failed.value
            session.runtime_failure_reason = str(exc)
            session.environment_summary_json = {
                **(session.environment_summary_json or {}),
                "readiness": "runtime_failed",
                "last_failure": str(exc),
            }
            db.add(session)
            mark_job_failed(db, job, str(exc))
            log_audit_event(
                db,
                event_type="runtime_provision_failed",
                target_type="session",
                target_id=session.id,
                actor_label="runtime_worker",
                payload={"error": str(exc)},
            )
            db.commit()
            return {"error": str(exc)}

        session = get_session_or_404(db, session.id)
        session.status = SessionStatus.ready.value
        session.runtime_failure_reason = None
        session.environment_summary_json = {
            **(session.environment_summary_json or {}),
            "readiness": "ready",
            "runtime_backend": workspace_summary.get("backend"),
            "runtime_limits": {
                "cpu": settings.runtime_session_cpu,
                "memory": settings.runtime_session_memory,
                "timeout_seconds": settings.runtime_session_timeout_seconds,
            },
            "track_content": track.content_metadata_json,
        }
        session.telemetry_summary_json = {
            **(session.telemetry_summary_json or {}),
            "workspace": {
                "status": workspace_summary["status"],
                "seeded_file_count": workspace_summary["seeded_file_count"],
                "backend": workspace_summary.get("backend"),
            },
        }
        db.add(session)
        mark_job_succeeded(db, job, workspace_summary)
        log_audit_event(
            db,
            event_type="runtime_provisioned",
            target_type="session",
            target_id=session.id,
            actor_label="runtime_worker",
            payload={"workspace_id": session.workspace_id, "backend": workspace_summary.get("backend")},
        )
        db.commit()
        return workspace_summary

    def _process_start_preview(self, db: Session, job: RuntimeJob) -> dict[str, Any]:
        session = get_session_or_404(db, job.target_id)
        track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
        if not track or not preview_enabled_for_track(track):
            raise RuntimeError("Preview is not configured for this track")

        handle = preview_manager.live_handle(session_id=session.id, workspace_id=session.workspace_id)
        try:
            summary = preview_manager.start(handle, preview_config_for_track(track), image_ref=track.container_image_ref)
            session.preview_summary_json = with_proxy_urls(summary, f"/api/preview/live/{session.id}")
            db.add(session)
            if session.preview_summary_json.get("status") == "ready":
                mark_job_succeeded(db, job, session.preview_summary_json)
            else:
                mark_job_failed(
                    db,
                    job,
                    session.preview_summary_json.get("error") or "Preview failed before readiness",
                    session.preview_summary_json,
                )
            log_audit_event(
                db,
                event_type="preview_started",
                target_type="session",
                target_id=session.id,
                actor_label="runtime_worker",
                payload={"status": session.preview_summary_json.get("status")},
            )
            db.commit()
            return session.preview_summary_json
        except PreviewUnavailableError as exc:
            session.preview_summary_json = {**(session.preview_summary_json or {}), "status": "failed", "error": str(exc)}
            db.add(session)
            mark_job_failed(db, job, str(exc))
            db.commit()
            return {"error": str(exc)}

    def _process_stop_preview(self, db: Session, job: RuntimeJob) -> dict[str, Any]:
        session = get_session_or_404(db, job.target_id)
        track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
        if not track or not preview_enabled_for_track(track):
            raise RuntimeError("Preview is not configured for this track")
        handle = preview_manager.live_handle(session_id=session.id, workspace_id=session.workspace_id)
        summary = preview_manager.stop(handle)
        session.preview_summary_json = with_proxy_urls(summary, f"/api/preview/live/{session.id}")
        db.add(session)
        mark_job_succeeded(db, job, session.preview_summary_json)
        log_audit_event(
            db,
            event_type="preview_stopped",
            target_type="session",
            target_id=session.id,
            actor_label="runtime_worker",
        )
        db.commit()
        return session.preview_summary_json

    def _process_freeze_submission(self, db: Session, job: RuntimeJob) -> dict[str, Any]:
        payload = job.payload_json or {}
        submission = get_submission_or_404(db, payload["submission_id"])
        report = get_report_or_404(db, payload["report_id"])
        session = get_session_or_404(db, submission.session_id)
        track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
        if not track:
            raise RuntimeError("Track version not found")

        if preview_enabled_for_track(track):
            live_handle = preview_manager.live_handle(session_id=session.id, workspace_id=session.workspace_id)
            live_summary = with_proxy_urls(preview_manager.stop(live_handle), f"/api/preview/live/{session.id}")
            session.preview_summary_json = live_summary
            db.add(session)
            db.commit()

        events = db.query(SessionEvent).filter(SessionEvent.session_id == session.id).order_by(SessionEvent.occurred_at.asc()).all()
        automated_override = payload.get("automated_result_override")
        automated_score = summarize_automated_score(events, automated_override)
        provenance_summary = summarize_provenance(events, session.started_at or utcnow(), utcnow())
        if isinstance(payload.get("candidate_reflection"), dict):
            provenance_summary["candidate_reflection"] = payload["candidate_reflection"]

        try:
            artifact_bundle = runtime_provisioner.create_submission_artifact(
                submission_id=submission.id,
                workspace_id=session.workspace_id,
                immutable_snapshot=payload.get("immutable_snapshot") or {},
            )
        except DockerUnavailableError as exc:
            session.status = SessionStatus.runtime_failed.value
            session.runtime_failure_reason = str(exc)
            session.environment_summary_json = {
                **(session.environment_summary_json or {}),
                "readiness": "runtime_failed",
                "last_failure": str(exc),
            }
            report.status = ReportStatus.flagged.value
            db.add(session)
            db.add(report)
            mark_job_failed(db, job, str(exc))
            db.commit()
            return {"error": str(exc)}

        session.status = SessionStatus.submitted.value
        session.ended_at = utcnow()
        session.telemetry_summary_json = summarize_events(db, session.id)
        session.integrity_summary_json = provenance_summary["integrity"]
        session.environment_summary_json = {**(session.environment_summary_json or {}), "readiness": "submitted"}

        preview_share_token = submission.preview_share_token or (secrets.token_urlsafe(16) if preview_enabled_for_track(track) else None)
        submission.artifact_uri = payload.get("artifact_uri") or artifact_bundle["artifact_uri"]
        submission.artifact_sha = payload.get("artifact_sha") or artifact_bundle["artifact_sha"]
        submission.build_log_uri = payload.get("build_log_uri") or artifact_bundle["build_log_uri"]
        submission.test_log_uri = payload.get("test_log_uri") or artifact_bundle["test_log_uri"]
        submission.artifact_manifest_uri = artifact_bundle["artifact_manifest_uri"]
        submission.immutable_snapshot_json = artifact_bundle["immutable_snapshot"]
        submission.automated_score_json = automated_score
        submission.provenance_summary_json = provenance_summary
        submission.evidence_summary_json = artifact_bundle["immutable_snapshot"].get("evidence_uris", {})
        submission.preview_share_token = preview_share_token
        submission.preview_summary_json = _default_preview_summary(track, submission.id, "frozen", f"/api/preview/frozen/{preview_share_token or submission.id}")
        submission.review_state = ReviewState.flagged.value if provenance_summary["integrity"]["review_signals"] else ReviewState.pending_review.value
        submission.benchmark_summary_json = calculate_benchmark_summary(db, submission)

        report.status = ReportStatus.flagged.value if submission.review_state == ReviewState.flagged.value else ReportStatus.pending_review.value
        report.candidate_summary_json = build_candidate_summary(track, session, submission)
        report.employer_summary_json = build_employer_summary(track, session, submission)
        report.review_summary_json = {
            "assignment_state": "unassigned",
            "escalation_state": EscalationState.flagged.value if submission.review_state == ReviewState.flagged.value else EscalationState.none.value,
            "publication_state": "draft",
        }

        if session.attempt_id:
            attempt = get_attempt_or_404(db, session.attempt_id)
            attempt.status = AttemptStatus.completed.value
            attempt.completed_at = utcnow()
            db.add(attempt)

        db.add(session)
        db.add(submission)
        db.add(report)
        mark_job_succeeded(db, job, {"submission_id": submission.id, "report_id": report.id})
        log_audit_event(
            db,
            event_type="submission_frozen",
            target_type="submission",
            target_id=submission.id,
            actor_label="runtime_worker",
            payload={"report_id": report.id},
        )
        db.commit()
        return {"submission_id": submission.id, "report_id": report.id}

    def _process_cleanup(self, db: Session, job: RuntimeJob) -> dict[str, Any]:
        result = execute_cleanup_pass()
        mark_job_succeeded(db, job, result)
        db.commit()
        return result


runtime_job_worker = RuntimeJobWorkerService()
