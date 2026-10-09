"""Durable deployment queue shared by manual, schedule and signed webhook invocations."""

from datetime import timedelta

from fastapi import HTTPException
from jsonschema import validate
from sqlalchemy import func, select, update

from factory.config import settings
from factory.db import SessionLocal, now, uid
from factory.models import AgentVersion, Deployment, DeploymentTrigger, ExecutionRun, Invocation, Membership, RuntimeJob
from factory.runtime import emit, execute
from factory.schemas import AgentSpec
from factory.security import Principal, audit, redact, require_write

RUNNABLE = ("PENDING", "RUNNING")


def actor_for(db, org_id, user_id):
    member = db.scalar(select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id))
    if not member or member.role not in ("admin", "editor"):
        raise PermissionError("Invocation authorization revoked")
    return Principal(user_id, org_id, member.role)


def enqueue(db, deployment_id, actor, input_data, idempotency_key):
    require_write(actor)
    deployment = db.scalar(
        select(Deployment).where(Deployment.id == deployment_id, Deployment.org_id == actor.org_id).with_for_update()
    )
    if not deployment:
        raise HTTPException(404, "Deployment not found")
    actor_for(db, actor.org_id, actor.user_id)
    previous = db.scalar(
        select(Invocation).where(
            Invocation.deployment_id == deployment.id, Invocation.idempotency_key == idempotency_key
        )
    )
    if previous:
        run = db.get(ExecutionRun, previous.run_id)
        if run.input != redact(input_data):
            raise HTTPException(409, "Idempotency key already used for different input")
        return run, db.scalar(select(RuntimeJob).where(RuntimeJob.invocation_id == previous.id))
    if not deployment.active:
        raise HTTPException(409, "Deployment is paused")
    version = db.get(AgentVersion, deployment.version_id)
    if (
        not version
        or version.org_id != actor.org_id
        or version.agent_id != deployment.agent_id
        or not version.approved_at
    ):
        raise PermissionError("Deployment version is not approved")
    spec = AgentSpec.model_validate(version.spec)
    validate(input_data, spec.input_schema)
    count = db.scalar(select(func.count()).select_from(Invocation).where(Invocation.deployment_id == deployment.id))
    if count >= deployment.policy.get("max_invocations", 1000):
        raise HTTPException(409, "Deployment invocation budget exhausted")
    reservation = (
        min(spec.max_cost, deployment.policy.get("max_cost", 1)) if settings().execution_mode == "live" else 0.0
    )
    if deployment.spent + deployment.reserved + reservation > deployment.policy.get("lifetime_max_cost", 10):
        raise HTTPException(409, "Deployment lifetime cost budget exhausted")
    deployment.reserved += reservation
    run = ExecutionRun(
        org_id=actor.org_id,
        version_id=version.id,
        mode=settings().execution_mode,
        input=redact(input_data),
        status="queued",
    )
    db.add(run)
    db.flush()
    invocation = Invocation(
        org_id=actor.org_id, deployment_id=deployment.id, idempotency_key=idempotency_key, run_id=run.id
    )
    db.add(invocation)
    db.flush()
    job = RuntimeJob(org_id=actor.org_id, invocation_id=invocation.id, actor_id=actor.user_id, reservation=reservation)
    db.add(job)
    db.flush()
    audit(db, actor, "deployment_invocation_enqueued", run.id, {"deployment_id": deployment.id, "job_id": job.id})
    emit(db, actor.org_id, "invocation_queued", {"job_id": job.id, "deployment_id": deployment.id}, run_id=run.id)
    return run, job


async def execute_job(db, job_id):
    owner = uid()
    claimed = db.execute(
        update(RuntimeJob)
        .where(
            RuntimeJob.id == job_id,
            RuntimeJob.state.in_(RUNNABLE),
            (RuntimeJob.lease_until.is_(None) | (RuntimeJob.lease_until < now())),
        )
        .values(
            lease_owner=owner,
            lease_until=now() + timedelta(seconds=settings().worker_lease_seconds),
            state="RUNNING",
            attempts=RuntimeJob.attempts + 1,
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    db.expire_all()
    if not claimed:
        return None
    job = db.scalar(
        select(RuntimeJob).where(RuntimeJob.id == job_id, RuntimeJob.lease_owner == owner).with_for_update()
    )
    invocation = db.get(Invocation, job.invocation_id)
    run = db.get(ExecutionRun, invocation.run_id)
    deployment = db.scalar(select(Deployment).where(Deployment.id == invocation.deployment_id).with_for_update())
    try:
        actor = actor_for(db, job.org_id, job.actor_id)
        if deployment.org_id != job.org_id or not deployment.active:
            raise PermissionError("Deployment paused or unauthorized")
        version = db.get(AgentVersion, run.version_id)
        if version.id != deployment.version_id or version.org_id != job.org_id or not version.approved_at:
            raise PermissionError("Invocation version is not approved")
        if job.attempts > settings().runtime_max_attempts:
            raise ValueError("Invocation retry budget exhausted")
        if run.status not in ("queued", "running"):
            # A committed result is never executed again, even if the queue lease is retried.
            job.state = "COMPLETED"
        else:
            await execute(
                db, version, run.input, mode=run.mode, run=run, max_cost=job.reservation if run.mode == "live" else None
            )
            job.state = "FAILED" if run.status == "failed" else "COMPLETED"
        audit(db, actor, "deployment_invoked", run.id)
    except (PermissionError, ValueError) as error:
        run.status = "failed"
        run.error = type(error).__name__
        job.state = "FAILED"
        job.error = type(error).__name__
        emit(db, job.org_id, "invocation_failed", {"error_type": type(error).__name__}, run_id=run.id)
    deployment.reserved = max(0, deployment.reserved - job.reservation)
    deployment.spent += run.metrics.get("cost", 0)
    job.reservation = 0
    job.lease_owner = None
    job.lease_until = None
    db.commit()
    return run


async def invocation_tick(session_factory=SessionLocal):
    with session_factory() as db:
        job_id = db.scalar(
            select(RuntimeJob.id)
            .where(
                RuntimeJob.state.in_(RUNNABLE), (RuntimeJob.lease_until.is_(None) | (RuntimeJob.lease_until < now()))
            )
            .order_by(RuntimeJob.created_at)
            .limit(1)
        )
        if not job_id:
            return False
        await execute_job(db, job_id)
        return True


def schedule_tick(session_factory=SessionLocal):
    with session_factory() as db:
        trigger = db.scalar(
            select(DeploymentTrigger)
            .join(Deployment, Deployment.id == DeploymentTrigger.deployment_id)
            .where(
                DeploymentTrigger.kind == "schedule",
                DeploymentTrigger.enabled.is_(True),
                DeploymentTrigger.next_run_at <= now(),
                Deployment.active.is_(True),
            )
            .order_by(DeploymentTrigger.next_run_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not trigger:
            return False
        scheduled_at = trigger.next_run_at
        slot = scheduled_at.isoformat()
        try:
            actor = actor_for(db, trigger.org_id, trigger.actor_id)
            # The unique invocation key makes a retried scheduling transaction idempotent.
            enqueue(db, trigger.deployment_id, actor, trigger.input, "schedule:" + trigger.id + ":" + slot)
            trigger.last_error = None
        except (HTTPException, PermissionError, ValueError) as error:
            trigger.last_error = type(error).__name__
            trigger.enabled = False
        # Coalesce missed slots after downtime instead of sending a burst of stale operations.
        trigger.next_run_at = now() + timedelta(seconds=trigger.interval_seconds)
        db.commit()
        return True
