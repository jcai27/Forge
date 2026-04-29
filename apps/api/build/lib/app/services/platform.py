from __future__ import annotations

import secrets
from collections import Counter
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import (
    CalibrationRun,
    EmployerReview,
    EventType,
    Report,
    ReportStatus,
    ReviewState,
    ReviewerAssignment,
    Session as CandidateSession,
    SessionEvent,
    SessionStatus,
    Submission,
    SubmissionVisibility,
    TrackVersion,
)
from app.schemas import CalibrationRunCreate, EmployerReviewCreate, ReviewerAssignmentCreate, SessionCreate, SessionEventCreate, SubmissionCreate


def list_active_tracks(db: Session) -> list[TrackVersion]:
    return db.query(TrackVersion).filter(TrackVersion.is_active.is_(True)).all()


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


def create_session(db: Session, payload: SessionCreate) -> CandidateSession:
    track = db.query(TrackVersion).filter(TrackVersion.id == payload.track_version_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track version not found")

    session = CandidateSession(
        id=f"session_{uuid4().hex[:12]}",
        user_id=payload.user_id,
        track_version_id=payload.track_version_id,
        workspace_id=f"ws_{uuid4().hex[:12]}",
        status=SessionStatus.active.value,
        started_at=datetime.utcnow(),
        last_activity_at=datetime.utcnow(),
        telemetry_summary_json={
            "event_counts": {},
            "active_minutes": 0,
            "ai_interactions": 0,
        },
        integrity_summary_json={"flags": [], "confidence_score": 100},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def append_session_event(db: Session, session_id: str, payload: SessionEventCreate) -> CandidateSession:
    session = get_session_or_404(db, session_id)
    if session.status == SessionStatus.submitted.value:
        raise HTTPException(status_code=409, detail="Session is already submitted")

    event = SessionEvent(
        id=f"evt_{uuid4().hex[:12]}",
        session_id=session.id,
        event_type=payload.event_type.value,
        occurred_at=payload.occurred_at or datetime.utcnow(),
        payload_json=payload.payload,
    )
    db.add(event)
    session.last_activity_at = event.occurred_at
    session.telemetry_summary_json = summarize_events(db, session.id)
    session.integrity_summary_json = summarize_integrity(db, session.id)
    db.commit()
    db.refresh(session)
    return session


def create_submission(db: Session, payload: SubmissionCreate) -> dict:
    session = get_session_or_404(db, payload.session_id)
    if session.status == SessionStatus.submitted.value:
        raise HTTPException(status_code=409, detail="Submission already exists for session")

    existing = db.query(Submission).filter(Submission.session_id == session.id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Submission already exists for session")

    track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track version not found")

    events = (
        db.query(SessionEvent)
        .filter(SessionEvent.session_id == session.id)
        .order_by(SessionEvent.occurred_at.asc())
        .all()
    )
    automated_score = summarize_automated_score(events, payload.automated_result_override.model_dump() if payload.automated_result_override else None)
    provenance_summary = summarize_provenance(events, session.started_at, datetime.utcnow())

    session.status = SessionStatus.submitted.value
    session.ended_at = datetime.utcnow()
    session.telemetry_summary_json = summarize_events(db, session.id)
    session.integrity_summary_json = provenance_summary["integrity"]

    submission = Submission(
        id=f"sub_{uuid4().hex[:12]}",
        session_id=session.id,
        track_version_id=session.track_version_id,
        user_id=session.user_id,
        artifact_uri=payload.artifact_uri,
        artifact_sha=payload.artifact_sha,
        build_log_uri=payload.build_log_uri,
        test_log_uri=payload.test_log_uri,
        immutable_snapshot_json=payload.immutable_snapshot,
        automated_score_json=automated_score,
        provenance_summary_json=provenance_summary,
        benchmark_summary_json={},
        visibility=payload.visibility.value,
        review_state=ReviewState.flagged.value if provenance_summary["integrity"]["flags"] else ReviewState.pending_review.value,
        share_token=secrets.token_urlsafe(16),
    )
    db.add(submission)
    db.flush()

    submission.benchmark_summary_json = calculate_benchmark_summary(db, submission)

    report = Report(
        id=f"report_{uuid4().hex[:12]}",
        submission_id=submission.id,
        visibility=payload.visibility.value,
        status=ReportStatus.flagged.value if submission.review_state == ReviewState.flagged.value else ReportStatus.pending_review.value,
        candidate_summary_json=build_candidate_summary(track, session, submission),
        employer_summary_json=build_employer_summary(track, session, submission),
        is_portable=False,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    db.refresh(submission)

    return {
        "session": serialize_session(session),
        "submission": serialize_submission(submission),
        "report": serialize_report(report),
    }


def create_employer_review(db: Session, payload: EmployerReviewCreate) -> dict:
    submission = get_submission_or_404(db, payload.submission_id)
    report = db.query(Report).filter(Report.submission_id == submission.id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found for submission")

    review = EmployerReview(
        id=f"review_{uuid4().hex[:12]}",
        organization_id=payload.organization_id,
        submission_id=payload.submission_id,
        reviewer_id=payload.reviewer_id,
        decision=payload.decision.value,
        confidence=payload.confidence,
        rubric_scores_json=[score.model_dump() for score in payload.rubric_scores],
        notes=payload.notes,
        completed_at=datetime.utcnow(),
    )
    db.add(review)

    submission.review_state = ReviewState.human_reviewed.value
    report.status = ReportStatus.ready.value
    report.is_portable = submission.visibility != SubmissionVisibility.private.value
    report.published_at = datetime.utcnow()

    employer_summary = report.employer_summary_json or {}
    employer_summary["human_review"] = {
        "decision": payload.decision.value,
        "confidence": payload.confidence,
        "rubric_scores": [score.model_dump() for score in payload.rubric_scores],
        "notes": payload.notes,
    }
    report.employer_summary_json = employer_summary

    candidate_summary = report.candidate_summary_json or {}
    candidate_summary["review_status"] = {
        "state": submission.review_state,
        "portable": report.is_portable,
        "published_at": report.published_at.isoformat() if report.published_at else None,
    }
    report.candidate_summary_json = candidate_summary

    db.commit()
    db.refresh(review)
    db.refresh(report)
    db.refresh(submission)

    return {
        "review": {
            "id": review.id,
            "decision": review.decision,
            "confidence": review.confidence,
            "completed_at": review.completed_at.isoformat() if review.completed_at else None,
        },
        "submission": serialize_submission(submission),
        "report": serialize_report(report),
    }


def create_reviewer_assignment(db: Session, payload: ReviewerAssignmentCreate) -> ReviewerAssignment:
    assignment = ReviewerAssignment(
        id=f"assignment_{uuid4().hex[:12]}",
        submission_id=payload.submission_id,
        reviewer_id=payload.reviewer_id,
        status=payload.status.value,
        due_at=payload.due_at,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def create_calibration_run(db: Session, payload: CalibrationRunCreate) -> CalibrationRun:
    pending_reviews = (
        db.query(EmployerReview)
        .join(Submission, Submission.id == EmployerReview.submission_id)
        .filter(Submission.track_version_id == payload.track_version_id)
        .all()
    )
    average_confidence = round(
        sum(review.confidence for review in pending_reviews) / len(pending_reviews), 2
    ) if pending_reviews else 0.0

    calibration = CalibrationRun(
        id=f"calibration_{uuid4().hex[:12]}",
        track_version_id=payload.track_version_id,
        initiated_by=payload.initiated_by,
        notes=payload.notes,
        sample_size=payload.sample_size,
        result_summary_json={
            "existing_reviews": len(pending_reviews),
            "average_confidence": average_confidence,
            "recommended_focus": "Inspect architecture and tradeoff scoring drift." if average_confidence < 0.7 else "Maintain weekly spot checks.",
        },
        completed_at=datetime.utcnow(),
    )
    db.add(calibration)
    db.commit()
    db.refresh(calibration)
    return calibration


def list_review_queue(db: Session) -> list[dict]:
    reports = db.query(Report).filter(Report.status != ReportStatus.ready.value).all()
    response = []
    for report in reports:
        submission = db.query(Submission).filter(Submission.id == report.submission_id).first()
        if not submission:
            continue
        response.append(
            {
                "report_id": report.id,
                "submission_id": submission.id,
                "review_state": submission.review_state,
                "automated_total_score": submission.automated_score_json.get("total_score", 0),
                "integrity_flags": submission.provenance_summary_json.get("integrity", {}).get("flags", []),
                "benchmark_percentile": submission.benchmark_summary_json.get("overall_percentile"),
            }
        )
    return response


def get_employer_report_by_token(db: Session, share_token: str) -> dict:
    submission = db.query(Submission).filter(Submission.share_token == share_token).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Report not found")

    report = db.query(Report).filter(Report.submission_id == submission.id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not report.is_portable:
        raise HTTPException(status_code=409, detail="Report is not portable until human review is complete")

    return {
        "report": serialize_report(report),
        "submission": serialize_submission(submission),
        "share_token": share_token,
    }


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


def summarize_integrity(db: Session, session_id: str) -> dict:
    session = get_session_or_404(db, session_id)
    events = db.query(SessionEvent).filter(SessionEvent.session_id == session_id).all()
    summary = summarize_provenance(events, session.started_at or datetime.utcnow(), datetime.utcnow())
    return summary["integrity"]


def summarize_automated_score(events: list[SessionEvent], override: dict | None = None) -> dict:
    override = override or {}
    test_events = [event for event in events if event.event_type == EventType.test_run.value]
    latest_test_payload = test_events[-1].payload_json if test_events else {}

    passed_tests = override.get("passed_tests")
    total_tests = override.get("total_tests")
    build_success = override.get("build_success")
    lint_passed = override.get("lint_passed")
    typecheck_passed = override.get("typecheck_passed")
    security_passed = override.get("security_passed")

    passed_tests = latest_test_payload.get("passed_tests", 0) if passed_tests is None else passed_tests
    total_tests = latest_test_payload.get("total_tests", 0) if total_tests is None else total_tests
    build_success = latest_test_payload.get("build_success", False) if build_success is None else build_success
    lint_passed = latest_test_payload.get("lint_passed", False) if lint_passed is None else lint_passed
    typecheck_passed = latest_test_payload.get("typecheck_passed", False) if typecheck_passed is None else typecheck_passed
    security_passed = latest_test_payload.get("security_passed", False) if security_passed is None else security_passed

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
            occurred_at=getattr(event, "occurred_at", None) or datetime.utcnow(),
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

    flags = []
    if paste_spikes:
        flags.append("large paste activity detected")
    if active_minutes and active_minutes < 20 and len(normalized_events) >= 8:
        flags.append("compressed editing activity")
    if counts[EventType.test_run.value] <= 1 and len(normalized_events) >= 10:
        flags.append("limited visible iteration before submission")

    confidence_score = max(55, 100 - (12 * len(flags)))
    timeline = []
    for event in normalized_events:
        if event.event_type in {EventType.test_run.value, EventType.checkpoint.value, EventType.terminal_command.value, EventType.ai_request.value}:
            label = event.payload_json.get("label") or event.payload_json.get("command") or event.event_type
            timeline.append(
                {
                    "at": event.occurred_at.isoformat(),
                    "type": event.event_type,
                    "label": label,
                }
            )

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
            "flags": flags,
            "confidence_score": confidence_score,
            "ai_usage_summary": "AI assistance used and summarized transparently." if ai_requests else "No AI requests logged.",
            "paste_spikes": paste_spikes,
        },
    }


def calculate_benchmark_summary(db: Session, submission: Submission) -> dict:
    peer_submissions = (
        db.query(Submission)
        .filter(Submission.track_version_id == submission.track_version_id)
        .all()
    )
    scores = [peer.automated_score_json.get("total_score", 0) for peer in peer_submissions]
    current = submission.automated_score_json.get("total_score", 0)
    if not scores:
        return {"overall_percentile": 100, "cohort_size": 1, "track_version_id": submission.track_version_id}

    percentile = round((sum(1 for score in scores if score <= current) / len(scores)) * 100, 2)
    return {
        "overall_percentile": percentile,
        "cohort_size": len(scores),
        "track_version_id": submission.track_version_id,
        "difficulty_band": "normalizing",
    }


def build_candidate_summary(track: TrackVersion, session: CandidateSession, submission: Submission) -> dict:
    return {
        "track": {
            "id": track.id,
            "title": track.title,
            "version": track.version,
            "duration_minutes": track.duration_minutes,
        },
        "submission": serialize_submission(submission),
        "timeline_summary": submission.provenance_summary_json,
        "review_status": {
            "state": submission.review_state,
            "portable": False,
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
        },
        "artifact_summary": {
            "workspace_id": session.workspace_id,
            "artifact_uri": submission.artifact_uri,
            "artifact_sha": submission.artifact_sha,
        },
        "dimension_breakdown": [
            {"dimension": "correctness", "score": automated.get("correctness_score", 0), "evidence": f"{automated.get('passed_tests', 0)}/{automated.get('total_tests', 0)} tests passed"},
            {"dimension": "quality", "score": automated.get("quality_score", 0), "evidence": "Build/lint/typecheck/security summary"},
            {"dimension": "provenance_confidence", "score": provenance.get("integrity", {}).get("confidence_score", 0), "evidence": provenance.get("work_pattern_summary", "")},
        ],
        "integrity_summary": provenance.get("integrity", {}),
        "benchmark_summary": submission.benchmark_summary_json,
        "recommended_question": "Ask the candidate why they chose their data model and where they would add observability next.",
    }


def serialize_session(session: CandidateSession) -> dict:
    return {
        "id": session.id,
        "user_id": session.user_id,
        "track_version_id": session.track_version_id,
        "workspace_id": session.workspace_id,
        "status": session.status,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "last_activity_at": session.last_activity_at.isoformat() if session.last_activity_at else None,
        "telemetry_summary": session.telemetry_summary_json,
        "integrity_summary": session.integrity_summary_json,
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
        "share_token": submission.share_token,
        "automated_score": submission.automated_score_json,
        "provenance_summary": submission.provenance_summary_json,
        "benchmark_summary": submission.benchmark_summary_json,
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
    }
