from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AuditEvent, RuntimeJob, RuntimeJobStatus


def utcnow() -> datetime:
    return datetime.utcnow()


def log_audit_event(
    db: Session,
    *,
    event_type: str,
    target_type: str,
    target_id: str,
    actor_id: str | None = None,
    actor_label: str = "",
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    audit_event = AuditEvent(
        id=f"audit_{uuid4().hex[:12]}",
        actor_id=actor_id,
        actor_label=actor_label,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        payload_json=payload or {},
    )
    db.add(audit_event)
    return audit_event


def create_runtime_job(
    db: Session,
    *,
    job_type: str,
    target_type: str,
    target_id: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> RuntimeJob:
    if idempotency_key:
        existing = db.query(RuntimeJob).filter(RuntimeJob.idempotency_key == idempotency_key).first()
        if existing:
            return existing

    job = RuntimeJob(
        id=f"job_{uuid4().hex[:12]}",
        job_type=job_type,
        target_type=target_type,
        target_id=target_id,
        payload_json=payload or {},
        idempotency_key=idempotency_key,
        status=RuntimeJobStatus.queued.value,
        available_at=utcnow(),
        max_attempts=settings.runtime_job_max_attempts,
        scheduled_at=utcnow(),
    )
    db.add(job)
    return job


def mark_job_running(db: Session, job: RuntimeJob) -> RuntimeJob:
    job.status = RuntimeJobStatus.running.value
    job.started_at = utcnow()
    job.heartbeat_at = utcnow()
    job.lease_expires_at = utcnow()
    job.attempts_count = (job.attempts_count or 0) + 1
    db.add(job)
    return job


def mark_job_succeeded(db: Session, job: RuntimeJob, result: dict[str, Any] | None = None) -> RuntimeJob:
    job.status = RuntimeJobStatus.succeeded.value
    job.result_json = result or {}
    job.error_text = None
    job.lease_expires_at = None
    job.heartbeat_at = utcnow()
    job.completed_at = utcnow()
    db.add(job)
    return job


def mark_job_failed(db: Session, job: RuntimeJob, error_text: str, result: dict[str, Any] | None = None) -> RuntimeJob:
    attempts = job.attempts_count or 0
    should_retry = attempts < (job.max_attempts or settings.runtime_job_max_attempts)
    if should_retry:
        backoff_seconds = min(300, 2 ** max(attempts, 1))
        job.status = RuntimeJobStatus.queued.value
        job.available_at = utcnow() + timedelta(seconds=backoff_seconds)
        job.scheduled_at = utcnow()
        job.completed_at = None
        job.lease_expires_at = None
    else:
        job.status = RuntimeJobStatus.poisoned.value
        job.completed_at = utcnow()
    job.result_json = result or {}
    job.error_text = error_text
    job.heartbeat_at = utcnow()
    db.add(job)
    return job
