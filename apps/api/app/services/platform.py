from __future__ import annotations

import secrets
from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    AssessmentAttempt,
    AssignmentStatus,
    AttemptStatus,
    CalibrationRun,
    EmployerReview,
    EscalationState,
    EventType,
    Report,
    ReportAccess,
    ReportAccessStatus,
    ReportAccessType,
    ReportStatus,
    ReviewDraftState,
    ReviewState,
    ReviewerAssignment,
    RuntimeJob,
    RuntimeJobStatus,
    Session as CandidateSession,
    SessionEvent,
    SessionStatus,
    Submission,
    SubmissionVisibility,
    TrackVersion,
)
from app.runtime.preview import PreviewUnavailableError, preview_manager
from app.runtime.provisioner import DockerUnavailableError, runtime_provisioner
from app.schemas import (
    AttemptCreate,
    CalibrationRunCreate,
    EmployerReviewCreate,
    ReviewerAssignmentCreate,
    ReviewerClaimCreate,
    ReviewPublishCreate,
    SessionCreate,
    SessionEventCreate,
    SubmissionCreate,
)
from app.services.runtime_control import (
    create_runtime_job,
    log_audit_event,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)


def utcnow() -> datetime:
    return datetime.utcnow()


def list_active_tracks(db: Session) -> list[TrackVersion]:
    return db.query(TrackVersion).filter(TrackVersion.is_active.is_(True)).all()


def get_attempt_or_404(db: Session, attempt_id: str) -> AssessmentAttempt:
    attempt = db.query(AssessmentAttempt).filter(AssessmentAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Assessment attempt not found")
    return attempt


def list_attempts(db: Session, *, status: str | None = None, limit: int = 20) -> list[AssessmentAttempt]:
    query = db.query(AssessmentAttempt).order_by(AssessmentAttempt.created_at.desc())
    if status:
        query = query.filter(AssessmentAttempt.status == status)
    return query.limit(limit).all()


def create_attempt(db: Session, payload: AttemptCreate) -> AssessmentAttempt:
    track = db.query(TrackVersion).filter(TrackVersion.id == payload.track_version_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track version not found")

    attempt = AssessmentAttempt(
        id=f"attempt_{uuid4().hex[:12]}",
        user_id=payload.user_id,
        organization_id=payload.organization_id,
        track_version_id=payload.track_version_id,
        candidate_label=payload.candidate_label or payload.user_id,
        invite_token=secrets.token_urlsafe(16),
        status=AttemptStatus.pending.value,
        notes=payload.notes,
        expires_at=payload.expires_at or utcnow() + timedelta(days=7),
    )
    db.add(attempt)
    log_audit_event(
        db,
        event_type="attempt_created",
        target_type="assessment_attempt",
        target_id=attempt.id,
        actor_label="internal_ops",
        payload={"track_version_id": payload.track_version_id, "user_id": payload.user_id},
    )
    db.commit()
    db.refresh(attempt)
    return attempt


def get_session_or_404(db: Session, session_id: str) -> CandidateSession:
    session = db.query(CandidateSession).filter(CandidateSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def get_submission_or_404(db: Session, submission_id: str) -> Submission:
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    return submission


def get_report_or_404(db: Session, report_id: str) -> Report:
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


def get_review_or_404(db: Session, review_id: str) -> EmployerReview:
    review = db.query(EmployerReview).filter(EmployerReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


def get_runtime_job(db: Session, session_id: str) -> RuntimeJob | None:
    return (
        db.query(RuntimeJob)
        .filter(RuntimeJob.target_type == "session", RuntimeJob.target_id == session_id)
        .order_by(RuntimeJob.created_at.desc())
        .first()
    )


def find_open_runtime_job(
    db: Session,
    *,
    target_type: str,
    target_id: str,
    job_type: str | None = None,
) -> RuntimeJob | None:
    query = db.query(RuntimeJob).filter(
        RuntimeJob.target_type == target_type,
        RuntimeJob.target_id == target_id,
        RuntimeJob.status.in_([RuntimeJobStatus.queued.value, RuntimeJobStatus.running.value]),
    )
    if job_type:
        query = query.filter(RuntimeJob.job_type == job_type)
    return query.order_by(RuntimeJob.created_at.desc()).first()


def ensure_session_editable(session: CandidateSession) -> None:
    if session.status in {
        SessionStatus.submitted.value,
        SessionStatus.expired.value,
        SessionStatus.cleaned.value,
    }:
        raise HTTPException(status_code=409, detail=f"Session is {session.status}")
    if session.status not in {SessionStatus.ready.value, SessionStatus.active.value}:
        raise HTTPException(status_code=409, detail="Session workspace is not ready")


def preview_config_for_track(track: TrackVersion) -> dict:
    return track.preview_config_json or {}


def preview_enabled_for_track(track: TrackVersion) -> bool:
    return bool(preview_config_for_track(track).get("enabled"))


def with_proxy_urls(summary: dict, proxy_base_path: str) -> dict:
    if not summary:
        return summary
    default_path = summary.get("default_path") or "/"
    if not str(default_path).startswith("/"):
        default_path = f"/{default_path}"
    enriched = {**summary}
    enriched["proxy_base_path"] = proxy_base_path
    enriched["default_url"] = f"{proxy_base_path}{default_path}"
    return enriched


def serialize_attempt(attempt: AssessmentAttempt) -> dict:
    return {
        "id": attempt.id,
        "user_id": attempt.user_id,
        "organization_id": attempt.organization_id,
        "track_version_id": attempt.track_version_id,
        "candidate_label": attempt.candidate_label,
        "invite_token": attempt.invite_token,
        "status": attempt.status,
        "notes": attempt.notes,
        "session_id": attempt.session_id,
        "expires_at": attempt.expires_at.isoformat() if attempt.expires_at else None,
        "opened_at": attempt.opened_at.isoformat() if attempt.opened_at else None,
        "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
    }


def serialize_job(job: RuntimeJob | None) -> dict | None:
    if not job:
        return None
    return {
        "id": job.id,
        "job_type": job.job_type,
        "target_type": job.target_type,
        "target_id": job.target_id,
        "status": job.status,
        "attempts_count": job.attempts_count,
        "payload": job.payload_json,
        "result": job.result_json,
        "error": job.error_text,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def serialize_session(session: CandidateSession, latest_job: RuntimeJob | None = None) -> dict:
    return {
        "id": session.id,
        "user_id": session.user_id,
        "track_version_id": session.track_version_id,
        "attempt_id": session.attempt_id,
        "workspace_id": session.workspace_id,
        "status": session.status,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "last_activity_at": session.last_activity_at.isoformat() if session.last_activity_at else None,
        "heartbeat_at": session.heartbeat_at.isoformat() if session.heartbeat_at else None,
        "expires_at": session.expires_at.isoformat() if session.expires_at else None,
        "runtime_failure_reason": session.runtime_failure_reason,
        "environment_summary": session.environment_summary_json,
        "telemetry_summary": session.telemetry_summary_json,
        "integrity_summary": session.integrity_summary_json,
        "preview_summary": session.preview_summary_json,
        "workspace": runtime_provisioner.workspace_summary(session.workspace_id),
        "latest_runtime_job": serialize_job(latest_job),
    }


def serialize_submission(submission: Submission) -> dict:
    return {
        "id": submission.id,
        "session_id": submission.session_id,
        "track_version_id": submission.track_version_id,
        "user_id": submission.user_id,
        "visibility": submission.visibility,
        "review_state": submission.review_state,
        "artifact_uri": submission.artifact_uri,
        "artifact_sha": submission.artifact_sha,
        "artifact_manifest_uri": submission.artifact_manifest_uri,
        "share_token": submission.share_token,
        "preview_share_token": submission.preview_share_token,
        "preview_summary": submission.preview_summary_json,
        "automated_score": submission.automated_score_json,
        "provenance_summary": submission.provenance_summary_json,
        "benchmark_summary": submission.benchmark_summary_json,
        "evidence_summary": submission.evidence_summary_json,
        "published_at": submission.published_at.isoformat() if submission.published_at else None,
    }


def serialize_report(report: Report) -> dict:
    return {
        "id": report.id,
        "submission_id": report.submission_id,
        "visibility": report.visibility,
        "status": report.status,
        "is_portable": report.is_portable,
        "published_at": report.published_at.isoformat() if report.published_at else None,
        "candidate_summary": report.candidate_summary_json,
        "employer_summary": report.employer_summary_json,
        "review_summary": report.review_summary_json,
    }


def serialize_review(review: EmployerReview) -> dict:
    return {
        "id": review.id,
        "organization_id": review.organization_id,
        "submission_id": review.submission_id,
        "reviewer_id": review.reviewer_id,
        "decision": review.decision,
        "confidence": review.confidence,
        "rubric_scores": review.rubric_scores_json,
        "notes": review.notes,
        "state": review.state,
        "escalation_state": review.escalation_state,
        "reviewer_annotations": review.reviewer_annotations_json,
        "draft_saved_at": review.draft_saved_at.isoformat() if review.draft_saved_at else None,
        "completed_at": review.completed_at.isoformat() if review.completed_at else None,
        "published_at": review.published_at.isoformat() if review.published_at else None,
    }


def _default_preview_summary(track: TrackVersion, session_or_submission_id: str, scope: str, proxy_base: str) -> dict:
    return with_proxy_urls(
        {
            "scope": scope,
            "subject_id": session_or_submission_id,
            "status": "not_started" if preview_enabled_for_track(track) else "disabled",
            "backend": None,
            "readiness_path": preview_config_for_track(track).get("readiness_path"),
            "default_path": preview_config_for_track(track).get("default_path"),
            "error": None,
        },
        proxy_base,
    )


def create_session(db: Session, payload: SessionCreate, *, user_id: str | None = None) -> CandidateSession:
    attempt: AssessmentAttempt | None = None
    if payload.attempt_id:
        attempt = get_attempt_or_404(db, payload.attempt_id)
        if attempt.session_id:
            existing = get_session_or_404(db, attempt.session_id)
            return existing
        user_id = attempt.user_id
        track_version_id = attempt.track_version_id
    else:
        user_id = user_id or ""
        track_version_id = payload.track_version_id or ""

    track = db.query(TrackVersion).filter(TrackVersion.id == track_version_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track version not found")

    session_id = f"session_{uuid4().hex[:12]}"
    workspace_id = f"ws_{uuid4().hex[:12]}"
    now = utcnow()
    session = CandidateSession(
        id=session_id,
        user_id=user_id,
        track_version_id=track_version_id,
        attempt_id=attempt.id if attempt else None,
        workspace_id=workspace_id,
        status=SessionStatus.queued.value,
        started_at=now,
        last_activity_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=settings.runtime_session_timeout_seconds),
        environment_summary_json={
            "readiness": "queued",
            "sandbox_policy": "container_required" if settings.environment.lower() == "production" else "development_auto",
            "preview_enabled": preview_enabled_for_track(track),
        },
        telemetry_summary_json={"event_counts": {}, "active_minutes": 0, "ai_interactions": 0},
        integrity_summary_json={"review_signals": [], "confidence_score": 100, "flags": []},
        preview_summary_json=_default_preview_summary(track, session_id, "live", f"/api/preview/live/{session_id}"),
    )
    db.add(session)
    if attempt:
        attempt.session_id = session.id
        attempt.status = AttemptStatus.session_launched.value
        attempt.opened_at = now
        db.add(attempt)

    log_audit_event(
        db,
        event_type="session_created",
        target_type="session",
        target_id=session.id,
        actor_label="candidate_launch",
        payload={"attempt_id": attempt.id if attempt else None, "track_version_id": track.id},
    )
    db.commit()
    db.refresh(session)
    return session


def provision_session_workspace(db: Session, session_id: str) -> tuple[CandidateSession, RuntimeJob]:
    session = get_session_or_404(db, session_id)
    track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track version not found")

    existing = find_open_runtime_job(db, target_type="session", target_id=session.id, job_type="provision_workspace")
    if existing:
        return session, existing

    job = create_runtime_job(
        db,
        job_type="provision_workspace",
        target_type="session",
        target_id=session.id,
        payload={"workspace_id": session.workspace_id, "track_version_id": track.id},
    )
    session.status = SessionStatus.queued.value
    session.environment_summary_json = {
        **(session.environment_summary_json or {}),
        "readiness": "queued",
        "track_content": track.content_metadata_json,
    }
    db.commit()
    db.refresh(session)
    db.refresh(job)
    return session, job


def retry_session_provision(db: Session, session_id: str) -> tuple[CandidateSession, RuntimeJob]:
    session = get_session_or_404(db, session_id)
    if session.status not in {
        SessionStatus.runtime_failed.value,
        SessionStatus.queued.value,
        SessionStatus.provisioning.value,
    }:
        raise HTTPException(status_code=409, detail="Session is not in a retryable state")
    session.status = SessionStatus.queued.value
    session.runtime_failure_reason = None
    session.environment_summary_json = {
        **(session.environment_summary_json or {}),
        "readiness": "queued",
        "last_failure": None,
    }
    db.add(session)
    db.commit()
    return provision_session_workspace(db, session_id)


def heartbeat_session(db: Session, session_id: str, at: datetime | None = None) -> CandidateSession:
    session = get_session_or_404(db, session_id)
    beat = at or utcnow()
    session.heartbeat_at = beat
    session.last_activity_at = beat
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def append_session_event(db: Session, session_id: str, payload: SessionEventCreate) -> CandidateSession:
    session = get_session_or_404(db, session_id)
    ensure_session_editable(session)

    event = SessionEvent(
        id=f"evt_{uuid4().hex[:12]}",
        session_id=session.id,
        event_type=payload.event_type.value,
        occurred_at=payload.occurred_at or utcnow(),
        payload_json=payload.payload,
    )
    db.add(event)
    try:
        runtime_details = runtime_provisioner.append_event(
            workspace_id=session.workspace_id,
            event_type=payload.event_type.value,
            occurred_at=event.occurred_at,
            payload=payload.payload,
        )
    except DockerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Workspace runtime unavailable: {exc}") from exc
    if runtime_details["command_result"]:
        event.payload_json["command_result"] = runtime_details["command_result"]
    if runtime_details["test_result"]:
        event.payload_json["runtime_result"] = runtime_details["test_result"]
    session.last_activity_at = event.occurred_at
    session.heartbeat_at = event.occurred_at
    session.telemetry_summary_json = summarize_events(db, session.id)
    session.telemetry_summary_json["workspace"] = {
        "workspace_id": session.workspace_id,
        "event_log_path": runtime_details["event_log_path"],
        "checkpoint": runtime_details["checkpoint"],
        "command_result": runtime_details["command_result"],
        "test_result": runtime_details["test_result"],
    }
    session.integrity_summary_json = summarize_integrity(db, session.id)
    db.commit()
    db.refresh(session)
    return session


def list_workspace_tree(db: Session, session_id: str) -> dict:
    session = get_session_or_404(db, session_id)
    if session.status not in {SessionStatus.ready.value, SessionStatus.active.value, SessionStatus.submitting.value, SessionStatus.submitted.value}:
        return {"session": serialize_session(session, get_runtime_job(db, session.id)), "items": []}
    items = runtime_provisioner.list_workspace_files(session.workspace_id)
    return {"session": serialize_session(session, get_runtime_job(db, session.id)), "items": items}


def read_workspace_file(db: Session, session_id: str, path: str) -> dict:
    session = get_session_or_404(db, session_id)
    ensure_session_editable(session)
    return {
        "session": serialize_session(session, get_runtime_job(db, session.id)),
        "file": runtime_provisioner.read_workspace_file(session.workspace_id, path),
    }


def write_workspace_file(
    db: Session,
    session_id: str,
    *,
    path: str,
    content: str,
    expected_updated_at: str | None = None,
) -> dict:
    session = get_session_or_404(db, session_id)
    ensure_session_editable(session)
    file_info = runtime_provisioner.write_workspace_file(
        session.workspace_id,
        path,
        content,
        expected_updated_at=expected_updated_at,
    )
    updated_session = append_session_event(
        db,
        session_id,
        SessionEventCreate(
            event_type=EventType.ide_edit,
            payload={"path": path, "chars": len(content), "line_count": len(content.splitlines()) or 1},
        ),
    )
    return {"session": serialize_session(updated_session, get_runtime_job(db, updated_session.id)), "file": file_info}


def delete_workspace_file(db: Session, session_id: str, path: str) -> dict:
    session = get_session_or_404(db, session_id)
    ensure_session_editable(session)
    runtime_provisioner.delete_workspace_file(session.workspace_id, path)
    updated_session = append_session_event(
        db,
        session_id,
        SessionEventCreate(
            event_type=EventType.ide_edit,
            payload={"path": path, "action": "delete"},
        ),
    )
    return {"session": serialize_session(updated_session, get_runtime_job(db, updated_session.id))}


def rename_workspace_file(db: Session, session_id: str, old_path: str, new_path: str) -> dict:
    session = get_session_or_404(db, session_id)
    ensure_session_editable(session)
    file_info = runtime_provisioner.rename_workspace_file(session.workspace_id, old_path, new_path)
    updated_session = append_session_event(
        db,
        session_id,
        SessionEventCreate(
            event_type=EventType.ide_edit,
            payload={"path": old_path, "new_path": new_path, "action": "rename"},
        ),
    )
    return {"session": serialize_session(updated_session, get_runtime_job(db, updated_session.id)), "file": file_info}


def search_workspace(db: Session, session_id: str, query: str) -> dict:
    session = get_session_or_404(db, session_id)
    ensure_session_editable(session)
    results = runtime_provisioner.search_workspace(session.workspace_id, query)
    return {"session": serialize_session(session, get_runtime_job(db, session.id)), "results": results}


def list_workspace_checkpoints(db: Session, session_id: str) -> list[dict]:
    session = get_session_or_404(db, session_id)
    ensure_session_editable(session)
    return runtime_provisioner.list_checkpoints(session.workspace_id)


def restore_checkpoint(db: Session, session_id: str, checkpoint_id: str) -> dict:
    session = get_session_or_404(db, session_id)
    ensure_session_editable(session)
    runtime_provisioner.restore_checkpoint(session.workspace_id, checkpoint_id)
    updated_session = append_session_event(
        db,
        session_id,
        SessionEventCreate(
            event_type=EventType.checkpoint,
            payload={"checkpoint_id": checkpoint_id, "action": "restore"},
        ),
    )
    return {"session": serialize_session(updated_session, get_runtime_job(db, updated_session.id))}


def run_workspace_command(db: Session, session_id: str, command: str) -> dict:
    updated_session = append_session_event(
        db,
        session_id,
        SessionEventCreate(event_type=EventType.terminal_command, payload={"command": command}),
    )
    workspace_summary = updated_session.telemetry_summary_json.get("workspace", {})
    return {"session": serialize_session(updated_session, get_runtime_job(db, updated_session.id)), "result": workspace_summary.get("command_result")}


def run_workspace_tests(db: Session, session_id: str, command: str) -> dict:
    updated_session = append_session_event(
        db,
        session_id,
        SessionEventCreate(event_type=EventType.test_run, payload={"command": command}),
    )
    workspace_summary = updated_session.telemetry_summary_json.get("workspace", {})
    return {"session": serialize_session(updated_session, get_runtime_job(db, updated_session.id)), "result": workspace_summary.get("test_result")}


def persist_session_preview(db: Session, session: CandidateSession, summary: dict) -> CandidateSession:
    session.preview_summary_json = summary
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def persist_submission_preview(db: Session, submission: Submission, summary: dict) -> Submission:
    submission.preview_summary_json = summary
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def start_live_preview(db: Session, session_id: str) -> dict:
    session = get_session_or_404(db, session_id)
    ensure_session_editable(session)
    track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
    if not track or not preview_enabled_for_track(track):
        raise HTTPException(status_code=409, detail="Preview is not configured for this track")
    existing = find_open_runtime_job(db, target_type="session", target_id=session.id, job_type="start_preview")
    if existing:
        return {"session": serialize_session(session, existing), "preview": session.preview_summary_json}
    job = create_runtime_job(
        db,
        job_type="start_preview",
        target_type="session",
        target_id=session.id,
        payload={"workspace_id": session.workspace_id},
    )
    session.preview_summary_json = {**session.preview_summary_json, "status": "starting", "error": None}
    db.commit()
    db.refresh(session)
    db.refresh(job)
    return {"session": serialize_session(session, job), "preview": session.preview_summary_json}


def get_live_preview_status(db: Session, session_id: str) -> dict:
    session = get_session_or_404(db, session_id)
    track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
    if not track or not preview_enabled_for_track(track):
        raise HTTPException(status_code=409, detail="Preview is not configured for this track")
    handle = preview_manager.live_handle(session_id=session.id, workspace_id=session.workspace_id)
    summary = preview_manager.get(handle)
    latest_job = get_runtime_job(db, session.id)
    if latest_job and latest_job.job_type in {"start_preview", "stop_preview"} and latest_job.status in {
        RuntimeJobStatus.queued.value,
        RuntimeJobStatus.running.value,
    }:
        current_preview = session.preview_summary_json or {}
        if current_preview.get("status") in {"starting", "stopping"}:
            if summary.get("status") == "not_started":
                return {"session": serialize_session(session, latest_job), "preview": current_preview}
            if current_preview.get("status") == "stopping" and summary.get("status") == "ready":
                return {"session": serialize_session(session, latest_job), "preview": current_preview}
    session = persist_session_preview(db, session, with_proxy_urls(summary, f"/api/preview/live/{session.id}"))
    return {"session": serialize_session(session, latest_job), "preview": session.preview_summary_json}


def stop_live_preview(db: Session, session_id: str) -> dict:
    session = get_session_or_404(db, session_id)
    track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
    if not track or not preview_enabled_for_track(track):
        raise HTTPException(status_code=409, detail="Preview is not configured for this track")
    existing = find_open_runtime_job(db, target_type="session", target_id=session.id, job_type="stop_preview")
    if existing:
        return {"session": serialize_session(session, existing), "preview": session.preview_summary_json}
    job = create_runtime_job(
        db,
        job_type="stop_preview",
        target_type="session",
        target_id=session.id,
        payload={"workspace_id": session.workspace_id},
    )
    session.preview_summary_json = {**(session.preview_summary_json or {}), "status": "stopping", "error": None}
    db.add(session)
    db.commit()
    db.refresh(session)
    db.refresh(job)
    return {"session": serialize_session(session, job), "preview": session.preview_summary_json}


def summarize_events(db: Session, session_id: str) -> dict:
    events = (
        db.query(SessionEvent)
        .filter(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.occurred_at.asc())
        .all()
    )
    counts = Counter(event.event_type for event in events)
    minute_buckets = {event.occurred_at.replace(second=0, microsecond=0) for event in events}
    return {
        "event_counts": dict(counts),
        "active_minutes": len(minute_buckets),
        "ai_interactions": counts[EventType.ai_request.value] + counts[EventType.ai_response.value],
        "latest_event_at": events[-1].occurred_at.isoformat() if events else None,
    }


def summarize_automated_score(events: list[SessionEvent], override: dict | None = None) -> dict:
    override = override or {}
    test_events = [event for event in events if event.event_type == EventType.test_run.value]
    latest_test_payload = test_events[-1].payload_json if test_events else {}
    runtime_result = latest_test_payload.get("runtime_result", {})

    passed_tests = runtime_result.get("passed_tests", latest_test_payload.get("passed_tests", 0)) if override.get("passed_tests") is None else override["passed_tests"]
    total_tests = runtime_result.get("total_tests", latest_test_payload.get("total_tests", 0)) if override.get("total_tests") is None else override["total_tests"]
    build_success = runtime_result.get("build_success", latest_test_payload.get("build_success", False)) if override.get("build_success") is None else override["build_success"]
    lint_passed = latest_test_payload.get("lint_passed", False) if override.get("lint_passed") is None else override["lint_passed"]
    typecheck_passed = latest_test_payload.get("typecheck_passed", False) if override.get("typecheck_passed") is None else override["typecheck_passed"]
    security_passed = latest_test_payload.get("security_passed", False) if override.get("security_passed") is None else override["security_passed"]

    correctness = round((passed_tests / total_tests) * 100, 2) if total_tests else 0.0
    quality_signals = [build_success, lint_passed, typecheck_passed, security_passed]
    quality = round((sum(1 for signal in quality_signals if signal) / len(quality_signals)) * 100, 2)
    total_score = round((correctness * 0.7) + (quality * 0.3), 2)
    return {
        "passed_tests": passed_tests,
        "total_tests": total_tests,
        "build_success": build_success,
        "lint_passed": lint_passed,
        "typecheck_passed": typecheck_passed,
        "security_passed": security_passed,
        "correctness_score": correctness,
        "quality_score": quality,
        "total_score": total_score,
    }


def summarize_provenance(events: list[SessionEvent], started_at: datetime, ended_at: datetime) -> dict:
    normalized_events = [
        SimpleNamespace(
            event_type=getattr(event, "event_type", None),
            occurred_at=getattr(event, "occurred_at", None) or utcnow(),
            payload_json=getattr(event, "payload_json", None) or getattr(event, "payload", None) or {},
        )
        for event in events
    ]
    normalized_events.sort(key=lambda event: event.occurred_at)
    counts = Counter(event.event_type for event in normalized_events)
    paste_spikes = sum(
        1
        for event in normalized_events
        if event.event_type == EventType.paste.value and event.payload_json.get("chars", 0) >= 400
    )
    ai_requests = counts[EventType.ai_request.value]
    duration_hours = round(max((ended_at - started_at).total_seconds(), 0) / 3600, 2)
    active_minutes = len({event.occurred_at.replace(second=0, microsecond=0) for event in normalized_events})

    review_signals: list[dict] = []
    if paste_spikes:
        review_signals.append({"key": "large_paste", "label": "large paste activity detected", "severity": "medium"})
    if active_minutes and active_minutes < 20 and len(normalized_events) >= 8:
        review_signals.append({"key": "compressed_activity", "label": "compressed editing activity", "severity": "medium"})
    if counts[EventType.test_run.value] <= 1 and len(normalized_events) >= 10:
        review_signals.append({"key": "limited_iteration", "label": "limited visible iteration before submission", "severity": "low"})

    confidence_score = max(55, 100 - (12 * len(review_signals)))
    timeline = []
    for event in normalized_events:
        if event.event_type in {
            EventType.test_run.value,
            EventType.checkpoint.value,
            EventType.terminal_command.value,
            EventType.ai_request.value,
        }:
            label = event.payload_json.get("label") or event.payload_json.get("command") or event.event_type
            timeline.append({"at": event.occurred_at.isoformat(), "type": event.event_type, "label": label})

    return {
        "session_duration_hours": duration_hours,
        "event_counts": dict(counts),
        "active_minutes": active_minutes,
        "timeline": timeline[:20],
        "work_pattern_summary": (
            f"Completed in {duration_hours}h with {counts[EventType.test_run.value]} test runs, "
            f"{counts[EventType.checkpoint.value]} checkpoints, and {ai_requests} AI requests."
        ),
        "integrity": {
            "review_signals": review_signals,
            "flags": [signal["label"] for signal in review_signals],
            "confidence_score": confidence_score,
            "ai_usage_summary": "AI assistance used and summarized transparently." if ai_requests else "No AI requests logged.",
            "paste_spikes": paste_spikes,
            "determination": "review_signal_only",
        },
    }


def summarize_integrity(db: Session, session_id: str) -> dict:
    session = get_session_or_404(db, session_id)
    events = db.query(SessionEvent).filter(SessionEvent.session_id == session_id).all()
    return summarize_provenance(events, session.started_at or utcnow(), utcnow())["integrity"]


def calculate_benchmark_summary(db: Session, submission: Submission) -> dict:
    track = db.query(TrackVersion).filter(TrackVersion.id == submission.track_version_id).first()
    benchmark_config = track.benchmark_config_json if track else {}
    cohort_minimum = int(benchmark_config.get("cohort_minimum", 1) or 1)
    peer_submissions = db.query(Submission).filter(Submission.track_version_id == submission.track_version_id).all()
    scores = [peer.automated_score_json.get("total_score", 0) for peer in peer_submissions]
    current = submission.automated_score_json.get("total_score", 0)
    cohort_size = len(scores)
    if cohort_size < cohort_minimum:
        return {
            "overall_percentile": None,
            "cohort_size": cohort_size,
            "track_version_id": submission.track_version_id,
            "benchmark_state": "insufficient_data",
            "cohort_minimum": cohort_minimum,
            "difficulty_band": "normalizing",
        }
    percentile = round((sum(1 for score in scores if score <= current) / cohort_size) * 100, 2)
    return {
        "overall_percentile": percentile,
        "cohort_size": cohort_size,
        "track_version_id": submission.track_version_id,
        "benchmark_state": "ready",
        "cohort_minimum": cohort_minimum,
        "difficulty_band": "normalizing",
    }


def _candidate_reflection(summary_note: str = "", tradeoff_note: str = "", unfinished_work_note: str = "", checklist: dict[str, bool] | None = None) -> dict:
    return {
        "summary_note": summary_note,
        "tradeoff_note": tradeoff_note,
        "unfinished_work_note": unfinished_work_note,
        "submission_checklist": checklist or {},
    }


def _candidate_reflection_from_submission(submission: Submission) -> dict:
    provenance = submission.provenance_summary_json or {}
    reflection = provenance.get("candidate_reflection")
    if isinstance(reflection, dict):
        return _candidate_reflection(
            str(reflection.get("summary_note", "")),
            str(reflection.get("tradeoff_note", "")),
            str(reflection.get("unfinished_work_note", "")),
            reflection.get("submission_checklist") if isinstance(reflection.get("submission_checklist"), dict) else {},
        )
    return _candidate_reflection()


def build_candidate_summary(track: TrackVersion, session: CandidateSession, submission: Submission) -> dict:
    return {
        "track": {
            "id": track.id,
            "title": track.title,
            "version": track.version,
            "duration_minutes": track.duration_minutes,
            "content_metadata": track.content_metadata_json,
        },
        "submission": serialize_submission(submission),
        "workspace": runtime_provisioner.workspace_summary(session.workspace_id),
        "preview": session.preview_summary_json,
        "candidate_reflection": _candidate_reflection_from_submission(submission),
        "timeline_summary": submission.provenance_summary_json,
        "review_status": {
            "state": submission.review_state,
            "portable": False,
            "publication_state": "awaiting_review",
        },
        "next_steps": [
            "Await human review before sharing with employers.",
            "Use the report to discuss architecture and debugging choices in interviews.",
        ],
    }


def build_employer_summary(track: TrackVersion, session: CandidateSession, submission: Submission) -> dict:
    automated = submission.automated_score_json
    provenance = submission.provenance_summary_json
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
            "artifact_uri": submission.artifact_uri,
            "artifact_sha": submission.artifact_sha,
            "artifact_manifest_uri": submission.artifact_manifest_uri,
            "workspace": runtime_provisioner.workspace_summary(session.workspace_id),
        },
        "dimension_breakdown": [
            {"dimension": "correctness", "score": automated.get("correctness_score", 0), "evidence": f"{automated.get('passed_tests', 0)}/{automated.get('total_tests', 0)} tests passed"},
            {"dimension": "quality", "score": automated.get("quality_score", 0), "evidence": "Build/lint/typecheck/security summary"},
            {"dimension": "provenance_confidence", "score": provenance.get("integrity", {}).get("confidence_score", 0), "evidence": provenance.get("work_pattern_summary", "")},
        ],
        "integrity_summary": provenance.get("integrity", {}),
        "benchmark_summary": submission.benchmark_summary_json,
        "candidate_reflection": _candidate_reflection_from_submission(submission),
        "preview_available": False,
        "preview_access_token": None,
        "preview_default_path": submission.preview_summary_json.get("default_url") if submission.preview_summary_json else None,
        "recommended_question": "Ask the candidate why they chose their data model and where they would add observability next.",
    }


def create_submission(db: Session, payload: SubmissionCreate) -> dict:
    session = get_session_or_404(db, payload.session_id)
    existing = db.query(Submission).filter(Submission.session_id == session.id).first()
    if existing:
        report = db.query(Report).filter(Report.submission_id == existing.id).first()
        return {
            "session": serialize_session(session, get_runtime_job(db, session.id)),
            "submission": serialize_submission(existing),
            "report": serialize_report(report) if report else None,
        }

    track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track version not found")

    session.status = SessionStatus.submitting.value
    job = create_runtime_job(
        db,
        job_type="freeze_submission",
        target_type="session",
        target_id=session.id,
        payload={"workspace_id": session.workspace_id},
    )
    submission_id = f"sub_{uuid4().hex[:12]}"
    preview_share_token = secrets.token_urlsafe(16) if preview_enabled_for_track(track) else None
    candidate_reflection = _candidate_reflection(
        payload.candidate_summary_note,
        payload.tradeoff_note,
        payload.unfinished_work_note,
        payload.submission_checklist,
    )
    submission = Submission(
        id=submission_id,
        session_id=session.id,
        track_version_id=session.track_version_id,
        user_id=session.user_id,
        artifact_uri=payload.artifact_uri,
        artifact_sha=payload.artifact_sha,
        build_log_uri=payload.build_log_uri,
        test_log_uri=payload.test_log_uri,
        artifact_manifest_uri=None,
        immutable_snapshot_json=payload.immutable_snapshot,
        automated_score_json={},
        provenance_summary_json={},
        benchmark_summary_json={"overall_percentile": None, "cohort_size": 0, "benchmark_state": "pending"},
        evidence_summary_json={},
        preview_summary_json=_default_preview_summary(track, submission_id, "frozen", f"/api/preview/frozen/{preview_share_token or submission_id}"),
        visibility=payload.visibility.value,
        review_state=ReviewState.pending_review.value,
        share_token=secrets.token_urlsafe(16),
        preview_share_token=preview_share_token,
    )
    db.add(submission)
    db.flush()
    report = Report(
        id=f"report_{uuid4().hex[:12]}",
        submission_id=submission.id,
        visibility=payload.visibility.value,
        status=ReportStatus.draft.value,
        candidate_summary_json={
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
            "candidate_reflection": candidate_reflection,
            "timeline_summary": {
                "work_pattern_summary": "Submission is finalizing. Artifact freezing and evidence assembly are still running.",
                "integrity": {
                    "flags": [],
                    "review_signals": [],
                    "confidence_score": 100,
                    "ai_usage_summary": "Pending final evidence assembly.",
                },
                "candidate_reflection": candidate_reflection,
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
        },
        employer_summary_json={
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
            "candidate_reflection": candidate_reflection,
            "benchmark_summary": {"overall_percentile": None, "cohort_size": 0, "benchmark_state": "pending"},
            "preview_available": False,
            "preview_access_token": None,
            "preview_default_path": None,
            "recommended_question": "Await finalized submission evidence before using this report.",
        },
        review_summary_json={
            "assignment_state": "unassigned",
            "escalation_state": EscalationState.none.value,
            "publication_state": "finalizing_submission",
        },
        is_portable=False,
    )
    db.add(report)
    job.payload_json = {
        **(job.payload_json or {}),
        "submission_id": submission.id,
        "report_id": report.id,
        "immutable_snapshot": payload.immutable_snapshot,
        "automated_result_override": payload.automated_result_override.model_dump() if payload.automated_result_override else None,
        "visibility": payload.visibility.value,
        "artifact_uri": payload.artifact_uri,
        "artifact_sha": payload.artifact_sha,
        "build_log_uri": payload.build_log_uri,
        "test_log_uri": payload.test_log_uri,
        "candidate_reflection": candidate_reflection,
    }
    db.add(job)
    db.commit()
    db.refresh(report)
    db.refresh(submission)
    db.refresh(session)
    db.refresh(job)
    return {"session": serialize_session(session, job), "submission": serialize_submission(submission), "report": serialize_report(report)}


def _build_assignment_snapshot(db: Session, submission_id: str) -> dict | None:
    assignment = (
        db.query(ReviewerAssignment)
        .filter(ReviewerAssignment.submission_id == submission_id)
        .order_by(ReviewerAssignment.created_at.desc())
        .first()
    )
    if not assignment:
        return None
    return {
        "id": assignment.id,
        "reviewer_id": assignment.reviewer_id,
        "status": assignment.status,
        "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
        "claimed_at": assignment.claimed_at.isoformat() if assignment.claimed_at else None,
        "completed_at": assignment.completed_at.isoformat() if assignment.completed_at else None,
    }


def create_reviewer_assignment(db: Session, payload: ReviewerAssignmentCreate) -> ReviewerAssignment:
    assignment = ReviewerAssignment(
        id=f"assignment_{uuid4().hex[:12]}",
        submission_id=payload.submission_id,
        reviewer_id=payload.reviewer_id,
        status=payload.status.value,
        due_at=payload.due_at or utcnow() + timedelta(hours=settings.review_sla_hours),
        claimed_at=utcnow() if payload.status == AssignmentStatus.claimed else None,
    )
    db.add(assignment)
    log_audit_event(
        db,
        event_type="review_assignment_created",
        target_type="submission",
        target_id=payload.submission_id,
        actor_id=payload.reviewer_id,
        actor_label="reviewer_assignment",
        payload={"assignment_id": assignment.id, "status": assignment.status},
    )
    db.commit()
    db.refresh(assignment)
    return assignment


def claim_reviewer_assignment(db: Session, payload: ReviewerClaimCreate, *, reviewer_id: str) -> ReviewerAssignment:
    existing = (
        db.query(ReviewerAssignment)
        .filter(ReviewerAssignment.submission_id == payload.submission_id, ReviewerAssignment.reviewer_id == reviewer_id)
        .order_by(ReviewerAssignment.created_at.desc())
        .first()
    )
    if existing:
        existing.status = AssignmentStatus.claimed.value
        existing.claimed_at = utcnow()
        existing.released_at = None
        if payload.due_at:
            existing.due_at = payload.due_at
        assignment = existing
    else:
        assignment = ReviewerAssignment(
            id=f"assignment_{uuid4().hex[:12]}",
            submission_id=payload.submission_id,
            reviewer_id=reviewer_id,
            status=AssignmentStatus.claimed.value,
            due_at=payload.due_at or utcnow() + timedelta(hours=settings.review_sla_hours),
            claimed_at=utcnow(),
        )
        db.add(assignment)

    submission = get_submission_or_404(db, payload.submission_id)
    if submission.review_state == ReviewState.pending_review.value:
        submission.review_state = ReviewState.in_review.value
        db.add(submission)
    log_audit_event(
        db,
        event_type="review_assignment_claimed",
        target_type="submission",
        target_id=payload.submission_id,
        actor_id=reviewer_id,
        actor_label="reviewer_claim",
        payload={"assignment_id": assignment.id},
    )
    db.commit()
    db.refresh(assignment)
    return assignment


def release_reviewer_assignment(db: Session, submission_id: str, reviewer_id: str) -> ReviewerAssignment:
    assignment = (
        db.query(ReviewerAssignment)
        .filter(ReviewerAssignment.submission_id == submission_id, ReviewerAssignment.reviewer_id == reviewer_id)
        .order_by(ReviewerAssignment.created_at.desc())
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Reviewer assignment not found")
    assignment.status = AssignmentStatus.released.value
    assignment.released_at = utcnow()
    db.add(assignment)
    log_audit_event(
        db,
        event_type="review_assignment_released",
        target_type="submission",
        target_id=submission_id,
        actor_id=reviewer_id,
        actor_label="reviewer_release",
        payload={"assignment_id": assignment.id},
    )
    db.commit()
    db.refresh(assignment)
    return assignment


def create_employer_review(db: Session, payload: EmployerReviewCreate, *, reviewer_id: str, organization_id: str) -> dict:
    submission = get_submission_or_404(db, payload.submission_id)
    report = db.query(Report).filter(Report.submission_id == submission.id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found for submission")
    track = db.query(TrackVersion).filter(TrackVersion.id == submission.track_version_id).first()

    review = (
        db.query(EmployerReview)
        .filter(EmployerReview.submission_id == submission.id, EmployerReview.reviewer_id == reviewer_id, EmployerReview.state != ReviewDraftState.published.value)
        .order_by(EmployerReview.created_at.desc())
        .first()
    )
    if not review:
        review = EmployerReview(
            id=f"review_{uuid4().hex[:12]}",
            organization_id=organization_id,
            submission_id=payload.submission_id,
            reviewer_id=reviewer_id,
        )
        db.add(review)

    review.decision = payload.decision.value
    review.confidence = payload.confidence
    review.rubric_scores_json = [score.model_dump() for score in payload.rubric_scores]
    review.notes = payload.notes
    review.reviewer_annotations_json = payload.reviewer_annotations
    review.escalation_state = payload.escalation_state or (
        EscalationState.second_review_required.value if submission.review_state == ReviewState.flagged.value else EscalationState.none.value
    )
    review.state = payload.state.value
    review.draft_saved_at = utcnow()

    submission.review_state = (
        ReviewState.second_review_required.value
        if review.escalation_state == EscalationState.second_review_required.value
        else ReviewState.in_review.value
    )
    db.add(submission)

    report.status = ReportStatus.flagged.value if review.escalation_state != EscalationState.none.value else ReportStatus.draft.value
    report.review_summary_json = {
        "assignment": _build_assignment_snapshot(db, submission.id),
        "escalation_state": review.escalation_state,
        "publication_state": "draft",
        "review_id": review.id,
        "reviewer_id": review.reviewer_id,
        "rubric_version": (track.content_metadata_json or {}).get("rubric_version") if track else "v1",
        "draft_saved_at": review.draft_saved_at.isoformat() if review.draft_saved_at else None,
        "reviewer_annotations": review.reviewer_annotations_json,
    }
    employer_summary = {**(report.employer_summary_json or {})}
    employer_summary["human_review"] = {
        "decision": payload.decision.value,
        "confidence": payload.confidence,
        "rubric_scores": [score.model_dump() for score in payload.rubric_scores],
        "notes": payload.notes,
        "reviewer_annotations": review.reviewer_annotations_json,
        "publication_state": "draft",
    }
    report.employer_summary_json = employer_summary

    assignment = (
        db.query(ReviewerAssignment)
        .filter(ReviewerAssignment.submission_id == submission.id, ReviewerAssignment.reviewer_id == reviewer_id)
        .order_by(ReviewerAssignment.created_at.desc())
        .first()
    )
    if assignment:
        assignment.status = AssignmentStatus.in_review.value
        db.add(assignment)

    log_audit_event(
        db,
        event_type="review_saved",
        target_type="submission",
        target_id=submission.id,
        actor_id=reviewer_id,
        actor_label="reviewer",
        payload={"review_id": review.id, "escalation_state": review.escalation_state},
    )
    db.commit()
    db.refresh(review)
    db.refresh(report)
    db.refresh(submission)
    return {"review": serialize_review(review), "submission": serialize_submission(submission), "report": serialize_report(report)}


def _access_expiry() -> datetime:
    return utcnow() + timedelta(hours=settings.report_access_ttl_hours)


def _create_report_access(db: Session, *, report_id: str, submission_id: str | None, access_type: str) -> ReportAccess:
    access = ReportAccess(
        id=f"access_{uuid4().hex[:12]}",
        report_id=report_id,
        submission_id=submission_id,
        access_type=access_type,
        token=secrets.token_urlsafe(24),
        status=ReportAccessStatus.active.value,
        issued_at=utcnow(),
        expires_at=_access_expiry(),
    )
    db.add(access)
    return access


def publish_employer_review(db: Session, payload: ReviewPublishCreate, *, actor_id: str) -> dict:
    review = get_review_or_404(db, payload.review_id)
    submission = get_submission_or_404(db, review.submission_id)
    report = db.query(Report).filter(Report.submission_id == submission.id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found for review")
    track = db.query(TrackVersion).filter(TrackVersion.id == submission.track_version_id).first()

    review.state = ReviewDraftState.published.value
    review.completed_at = utcnow()
    review.published_at = utcnow()
    db.add(review)

    submission.review_state = (
        ReviewState.second_review_required.value
        if review.escalation_state == EscalationState.second_review_required.value
        else ReviewState.human_reviewed.value
    )
    submission.visibility = payload.visibility.value
    submission.published_at = utcnow()
    db.add(submission)

    report.status = ReportStatus.ready.value if review.escalation_state == EscalationState.none.value else ReportStatus.flagged.value
    report.is_portable = payload.visibility != SubmissionVisibility.private.value and review.escalation_state == EscalationState.none.value
    report.published_at = utcnow()
    report.published_review_id = review.id

    report_access: ReportAccess | None = None
    preview_access: ReportAccess | None = None
    if report.is_portable:
        report_access = _create_report_access(db, report_id=report.id, submission_id=submission.id, access_type=ReportAccessType.report.value)
        if submission.preview_share_token and track and preview_enabled_for_track(track):
            preview_access = _create_report_access(db, report_id=report.id, submission_id=submission.id, access_type=ReportAccessType.preview.value)

    report.review_summary_json = {
        **(report.review_summary_json or {}),
        "publication_state": "published" if report.is_portable else "restricted",
        "published_review_id": review.id,
        "published_at": report.published_at.isoformat() if report.published_at else None,
        "reviewer_annotations": review.reviewer_annotations_json,
        "access": {
            "report_token": report_access.token if report_access else None,
            "preview_token": preview_access.token if preview_access else None,
            "expires_at": report_access.expires_at.isoformat() if report_access and report_access.expires_at else None,
        },
    }
    employer_summary = {**(report.employer_summary_json or {})}
    employer_summary["human_review"] = {
        "decision": review.decision,
        "confidence": review.confidence,
        "rubric_scores": review.rubric_scores_json,
        "notes": review.notes,
        "reviewer_annotations": review.reviewer_annotations_json,
        "publication_state": "published" if report.is_portable else "restricted",
    }
    employer_summary["preview_available"] = bool(report.is_portable and preview_access and track and preview_enabled_for_track(track))
    employer_summary["preview_access_token"] = preview_access.token if preview_access else None
    employer_summary["preview_share_token"] = preview_access.token if preview_access else None
    employer_summary["preview_default_path"] = submission.preview_summary_json.get("default_url") if submission.preview_summary_json else None
    employer_summary["report_access_token"] = report_access.token if report_access else None
    report.employer_summary_json = employer_summary

    candidate_summary = {**(report.candidate_summary_json or {})}
    candidate_summary["review_status"] = {
        "state": submission.review_state,
        "portable": report.is_portable,
        "published_at": report.published_at.isoformat() if report.published_at else None,
    }
    report.candidate_summary_json = candidate_summary
    db.add(report)

    assignment = (
        db.query(ReviewerAssignment)
        .filter(ReviewerAssignment.submission_id == submission.id, ReviewerAssignment.reviewer_id == review.reviewer_id)
        .order_by(ReviewerAssignment.created_at.desc())
        .first()
    )
    if assignment:
        assignment.status = AssignmentStatus.completed.value
        assignment.completed_at = utcnow()
        db.add(assignment)

    log_audit_event(
        db,
        event_type="review_published",
        target_type="report",
        target_id=report.id,
        actor_id=actor_id,
        actor_label="review_publisher",
        payload={"review_id": review.id, "portable": report.is_portable},
    )
    db.commit()
    db.refresh(review)
    db.refresh(report)
    db.refresh(submission)
    return {"review": serialize_review(review), "submission": serialize_submission(submission), "report": serialize_report(report)}


def revoke_report_access(db: Session, token: str, *, actor_id: str, reason: str = "") -> ReportAccess:
    access = db.query(ReportAccess).filter(ReportAccess.token == token).first()
    if not access:
        raise HTTPException(status_code=404, detail="Report access token not found")
    access.status = ReportAccessStatus.revoked.value
    access.revoked_at = utcnow()
    db.add(access)
    report = get_report_or_404(db, access.report_id)
    if report.status == ReportStatus.ready.value:
        report.status = ReportStatus.revoked.value
        db.add(report)
    log_audit_event(
        db,
        event_type="report_access_revoked",
        target_type="report_access",
        target_id=access.id,
        actor_id=actor_id,
        actor_label="internal_ops",
        payload={"reason": reason, "token": token},
    )
    db.commit()
    db.refresh(access)
    return access


def list_review_queue(db: Session) -> list[dict]:
    reports = db.query(Report).filter(Report.status != ReportStatus.ready.value).all()
    response: list[dict] = []
    for report in reports:
        submission = db.query(Submission).filter(Submission.id == report.submission_id).first()
        if not submission:
            continue
        review_summary = report.review_summary_json or {}
        review = (
            db.query(EmployerReview)
            .filter(EmployerReview.submission_id == submission.id)
            .order_by(EmployerReview.updated_at.desc())
            .first()
        )
        assignment = _build_assignment_snapshot(db, submission.id)
        due_at = assignment["due_at"] if assignment else None
        sla_state = "unassigned"
        if due_at:
            sla_state = "overdue" if datetime.fromisoformat(due_at) < utcnow() else "on_time"
        accesses = db.query(ReportAccess).filter(ReportAccess.report_id == report.id).all()
        response.append(
            {
                "report_id": report.id,
                "submission_id": submission.id,
                "review_id": review.id if review else None,
                "review_state": submission.review_state,
                "report_status": report.status,
                "automated_total_score": submission.automated_score_json.get("total_score", 0),
                "integrity_flags": submission.provenance_summary_json.get("integrity", {}).get("flags", []),
                "review_signals": submission.provenance_summary_json.get("integrity", {}).get("review_signals", []),
                    "benchmark_percentile": submission.benchmark_summary_json.get("overall_percentile"),
                    "benchmark_state": submission.benchmark_summary_json.get("benchmark_state"),
                    "assignment": assignment,
                    "sla_state": sla_state,
                    "escalation_state": review.escalation_state if review else review_summary.get("escalation_state"),
                    "publication_state": review_summary.get("publication_state"),
                    "portable": report.is_portable,
                "access_tokens": [
                    {
                        "token": access.token,
                        "access_type": access.access_type,
                        "status": access.status,
                        "expires_at": access.expires_at.isoformat() if access.expires_at else None,
                    }
                    for access in accesses
                ],
            }
        )
    return response


def get_internal_report_detail(db: Session, report_id: str) -> dict:
    report = get_report_or_404(db, report_id)
    submission = get_submission_or_404(db, report.submission_id)
    session = get_session_or_404(db, submission.session_id)
    review = (
        db.query(EmployerReview)
        .filter(EmployerReview.submission_id == submission.id)
        .order_by(EmployerReview.updated_at.desc())
        .first()
    )
    accesses = db.query(ReportAccess).filter(ReportAccess.report_id == report.id).all()

    return {
        "report": serialize_report(report),
        "submission": serialize_submission(submission),
        "session": serialize_session(session, get_runtime_job(db, session.id)),
        "review": serialize_review(review) if review else None,
        "assignment": _build_assignment_snapshot(db, submission.id),
        "access_tokens": [
            {
                "token": access.token,
                "access_type": access.access_type,
                "status": access.status,
                "expires_at": access.expires_at.isoformat() if access.expires_at else None,
            }
            for access in accesses
        ],
    }


def _active_report_access(db: Session, token: str, access_type: str) -> ReportAccess:
    access = db.query(ReportAccess).filter(ReportAccess.token == token, ReportAccess.access_type == access_type).first()
    if not access:
        raise HTTPException(status_code=404, detail="Report access not found")
    if access.status != ReportAccessStatus.active.value:
        raise HTTPException(status_code=409, detail="Report access is not active")
    if access.expires_at and access.expires_at < utcnow():
        access.status = ReportAccessStatus.expired.value
        db.add(access)
        db.commit()
        raise HTTPException(status_code=409, detail="Report access has expired")
    access.last_accessed_at = utcnow()
    db.add(access)
    db.commit()
    db.refresh(access)
    return access


def get_employer_report_by_token(db: Session, share_token: str) -> dict:
    access = _active_report_access(db, share_token, ReportAccessType.report.value)
    report = get_report_or_404(db, access.report_id)
    submission = get_submission_or_404(db, report.submission_id)
    if not report.is_portable:
        raise HTTPException(status_code=409, detail="Report is not portable until human review is complete")
    return {"report": serialize_report(report), "submission": serialize_submission(submission), "share_token": share_token}


def get_frozen_preview_by_token(db: Session, preview_share_token: str) -> dict:
    access = _active_report_access(db, preview_share_token, ReportAccessType.preview.value)
    report = get_report_or_404(db, access.report_id)
    submission = get_submission_or_404(db, access.submission_id or report.submission_id)
    if not report.is_portable:
        raise HTTPException(status_code=409, detail="Frozen preview is unavailable until the report is portable")
    track = db.query(TrackVersion).filter(TrackVersion.id == submission.track_version_id).first()
    if not track or not preview_enabled_for_track(track):
        raise HTTPException(status_code=409, detail="Preview is not configured for this track")
    handle = preview_manager.frozen_handle(submission_id=submission.id)
    summary = preview_manager.get(handle)
    if summary.get("status") != "ready":
        try:
            summary = preview_manager.start(handle, preview_config_for_track(track), image_ref=track.container_image_ref)
        except PreviewUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    summary = with_proxy_urls(summary, f"/api/preview/frozen/{preview_share_token}")
    submission = persist_submission_preview(db, submission, summary)
    return {"preview": submission.preview_summary_json, "submission": serialize_submission(submission), "report": serialize_report(report), "preview_share_token": preview_share_token}


def create_calibration_run(db: Session, payload: CalibrationRunCreate) -> CalibrationRun:
    pending_reviews = (
        db.query(EmployerReview)
        .join(Submission, Submission.id == EmployerReview.submission_id)
        .filter(Submission.track_version_id == payload.track_version_id, EmployerReview.state == ReviewDraftState.published.value)
        .all()
    )
    average_confidence = round(sum(review.confidence for review in pending_reviews) / len(pending_reviews), 2) if pending_reviews else 0.0
    track = db.query(TrackVersion).filter(TrackVersion.id == payload.track_version_id).first()
    calibration = CalibrationRun(
        id=f"calibration_{uuid4().hex[:12]}",
        track_version_id=payload.track_version_id,
        initiated_by=payload.initiated_by,
        notes=payload.notes,
        sample_size=payload.sample_size,
        rubric_version=(track.content_metadata_json or {}).get("rubric_version", "v1") if track else "v1",
        result_summary_json={
            "existing_reviews": len(pending_reviews),
            "average_confidence": average_confidence,
            "recommended_focus": "Inspect architecture and tradeoff scoring drift." if average_confidence < 0.7 else "Maintain weekly spot checks.",
        },
        completed_at=utcnow(),
    )
    db.add(calibration)
    db.commit()
    db.refresh(calibration)
    return calibration


def cleanup_expired_workspaces() -> dict:
    return runtime_provisioner.cleanup_expired_workspaces()


def queue_runtime_cleanup(db: Session, *, trigger: str = "manual") -> dict:
    from app.services.runtime_worker import enqueue_cleanup_job

    job = enqueue_cleanup_job(db, trigger=trigger)
    return {"job": serialize_job(job)}


def get_runtime_status() -> dict:
    from app.services.runtime_worker import runtime_job_worker

    runtime = runtime_provisioner.runtime_status()
    runtime["preview"] = preview_manager.runtime_status()
    runtime["worker"] = runtime_job_worker.status()
    return runtime


def list_runtime_workspaces(limit: int = 10) -> list[dict]:
    return runtime_provisioner.list_workspace_summaries(limit=limit)


def list_runtime_previews(limit: int = 10) -> list[dict]:
    return preview_manager.list_preview_summaries(limit=limit)
