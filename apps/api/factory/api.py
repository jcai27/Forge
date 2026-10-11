import asyncio
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import UTC, timedelta
from typing import Literal

from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from jsonschema import Draft202012Validator, validate
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonValidationError
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from factory import models as m
from factory.builder import available_tools, design, enforce_spec_scope, infer_template, persist_version
from factory.config import mode_for, settings
from factory.connectors import FileConnector, check_connection, discover_connection
from factory.db import get_db, now
from factory.fixtures import fictional_data, seed_business, seed_suite
from factory.intake import (
    IntakeError,
    add_document,
    attach_dataset,
    fetch_dataset,
    parse_records,
    remove_dataset,
    truth_source,
)
from factory.memberships import router as membership_router
from factory.proposals import ProposalError, approve_proposal, create_proposal, openapi_to_config
from factory.release import dossier, feedback_candidates, shadow_run
from factory.runtime import emit, resolve_approval
from factory.schemas import (
    AddDocument,
    AgentSpec,
    AttachDataset,
    Budget,
    CreateAgent,
    CreateCase,
    CreateConnection,
    CreateProject,
    CreateTrigger,
    HumanReview,
    Invoke,
    Login,
    Reconciliation,
    RedirectBuild,
    Register,
    TestDesign,
    TriggerUpdate,
)
from factory.security import (
    SECRET_KEYS,
    Principal,
    audit,
    encrypt,
    owned,
    passwords,
    principal,
    redact,
    redact_tenant,
    require_admin,
    require_write,
    token_for,
)
from factory.workflow import TERMINAL, control, new_job


@asynccontextmanager
async def lifespan(app):
    # Production startup runs Alembic externally, never implicit schema mutations.
    if settings().environment == "development":
        from pathlib import Path

        from alembic import command
        from alembic.config import Config

        directory = Path(__file__).resolve().parents[1]
        migration_config = Config(str(directory / "alembic.ini"))
        migration_config.set_main_option("script_location", str(directory / "migrations"))
        command.upgrade(migration_config, "head")
    yield


app = FastAPI(title="Agent Factory", version="0.1.0", lifespan=lifespan)
app.include_router(membership_router)


@app.exception_handler(HTTPException)
async def http_error(request, error):
    return JSONResponse(
        status_code=error.status_code, content={"error": {"code": str(error.status_code), "message": str(error.detail)}}
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    errors = [{"location": list(e["loc"]), "type": e["type"], "message": e["msg"]} for e in error.errors()]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "validation_error", "message": "Invalid request", "details": errors}},
    )


@app.exception_handler(JsonValidationError)
async def json_validation_error(request, error):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "schema_validation_error",
                "message": "Input does not match the configured JSON Schema",
                "path": list(error.absolute_path),
            }
        },
    )


@app.exception_handler(SchemaError)
async def json_schema_error(request, error):
    return JSONResponse(
        status_code=422, content={"error": {"code": "invalid_schema", "message": "Configured JSON Schema is invalid"}}
    )


@app.exception_handler(ValueError)
async def value_error(request, error):
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "invalid_operation",
                "message": "Operation could not be completed; check configuration and resource state",
            }
        },
    )


@app.exception_handler(IntegrityError)
async def conflict_error(request, error):
    return JSONResponse(
        status_code=409,
        content={"error": {"code": "conflict", "message": "Resource already exists or was concurrently modified"}},
    )


@app.exception_handler(PermissionError)
async def permission_error(request, error):
    return JSONResponse(
        status_code=403, content={"error": {"code": "permission_denied", "message": "Operation is not authorized"}}
    )


# Local development fallback. Production requires Redis and fails closed if unavailable.
limits = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    identity = request.client.host if request.client else "unknown"
    scope = "auth" if request.url.path in {"/auth/login", "/auth/register", "/auth/demo"} else "api"
    limit = 30 if scope == "auth" else 500
    bucket = f"{scope}:{identity}:{int(time.time() / 60)}"
    allowed = True
    if settings().environment == "production":
        import redis.asyncio as redis

        client = redis.from_url(settings().redis_url)
        try:
            count = await client.incr(bucket)
            if count == 1:
                await client.expire(bucket, 65)
            allowed = count <= limit
        except Exception:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {"code": "rate_limit_unavailable", "message": "Request protection temporarily unavailable"}
                },
                headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
            )
        finally:
            await client.aclose()
    else:
        queue = limits[f"{scope}:{identity}"]
        current = time.monotonic()
        while queue and queue[0] < current - 60:
            queue.popleft()
        allowed = len(queue) < limit
        queue.append(current)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "rate_limited", "message": "Request limit exceeded"}},
            headers={"Retry-After": "60", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


# CORS wraps rate protection so denied requests remain readable by approved browsers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
)


def serialize(row, org_id=None):
    result = {}
    for column in row.__table__.columns:
        if column.name in ("password_hash", "encrypted_secret", "token_hash", "lease_owner", "lease_until"):
            continue
        value = getattr(row, column.name)
        if hasattr(value, "isoformat"):
            # Times are stored in UTC, and SQLite returns them without saying so. A browser reads a
            # bare timestamp as local time, which shifts every displayed time by the viewer's offset.
            if getattr(value, "tzinfo", "absent") is None:
                value = value.replace(tzinfo=UTC)
            value = value.isoformat()
        result[column.name] = value
    org_id = org_id or getattr(row, "org_id", None) or (row.id if isinstance(row, m.Organization) else None)
    db = object_session(row)
    result = redact_tenant(db, org_id, result) if db is not None and org_id else redact(result)
    if isinstance(row, (m.Connection, m.DeploymentTrigger)):
        result["has_secret"] = bool(row.encrypted_secret)
    return result


def collection(db, cls, actor, offset=0, limit=50, predicates=()):
    query = select(cls).where(cls.org_id == actor.org_id, *predicates)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(cls.created_at.desc(), cls.id).offset(offset).limit(limit))
    return {"items": [serialize(row) for row in rows], "total": total, "offset": offset, "limit": limit}


DB = Depends(get_db)
ACTOR = Depends(principal)
OFFSET = Query(0, ge=0)
LIMIT = Query(50, ge=1, le=200)


@app.get("/health")
def health():
    return {"status": "ok", "execution_mode": settings().execution_mode}


@app.post("/auth/register", status_code=201)
def register(body: Register, db=DB):
    if "@" not in body.email:
        raise HTTPException(422, "Valid email required")
    org = m.Organization(name=body.organization)
    user = m.User(email=body.email.lower().strip(), password_hash=passwords.hash(body.password))
    db.add_all([org, user])
    db.flush()
    db.add(m.Membership(org_id=org.id, user_id=user.id, role="admin"))
    audit(db, Principal(user.id, org.id, "admin"), "organization_created", org.id)
    db.commit()
    return {"token": token_for(user.id, org.id), "organization": serialize(org), "user": serialize(user, org.id)}


@app.post("/auth/login")
def login(body: Login, db=DB):
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower().strip()))
    try:
        if not user:
            # Consume a comparable hash verification path for unknown accounts.
            passwords.verify(passwords.hash("unknown-account-placeholder"), body.password)
            raise VerificationError("Invalid credentials")
        passwords.verify(user.password_hash, body.password)
    except VerificationError:
        raise HTTPException(401, "Invalid credentials") from None
    query = select(m.Membership).where(m.Membership.user_id == user.id)
    if body.org_id:
        query = query.where(m.Membership.org_id == body.org_id)
    member = db.scalar(query.order_by(m.Membership.created_at))
    if not member:
        raise HTTPException(403, "No organization membership")
    return {
        "token": token_for(user.id, member.org_id),
        "user": serialize(user, member.org_id),
        "organization": serialize(db.get(m.Organization, member.org_id)),
    }


@app.get("/auth/me")
def me(actor=ACTOR, db=DB):
    memberships = db.scalars(select(m.Membership).where(m.Membership.user_id == actor.user_id))
    return {
        "user": serialize(db.get(m.User, actor.user_id), actor.org_id),
        "organization": serialize(db.get(m.Organization, actor.org_id)),
        "role": actor.role,
        "memberships": [
            {**serialize(row), "organization_name": db.get(m.Organization, row.org_id).name} for row in memberships
        ],
        "execution_mode": settings().execution_mode,
        "model": settings().openai_model,
    }


@app.post("/auth/demo")
async def demo(db=DB):
    if settings().environment != "development":
        raise HTTPException(404, "Not found")
    user = db.scalar(select(m.User).where(m.User.email == "demo@agentfactory.local"))
    if not user:
        org = m.Organization(name="Northstar Operations")
        user = m.User(email="demo@agentfactory.local", password_hash=passwords.hash("local-demo-password"))
        db.add_all([org, user])
        db.flush()
        db.add(m.Membership(org_id=org.id, user_id=user.id, role="admin"))
        db.add(m.Project(org_id=org.id, name="Operations Lab", description="Isolated fictional business workspace"))
        connection = m.Connection(
            org_id=org.id,
            name="Fictional Business ERP",
            kind="fixture",
            permissions={"read": True, "write": True},
            status="connected",
        )
        db.add(connection)
        db.flush()
        seed_business(db, org.id)
        await discover_connection(db, connection)
        db.commit()
    member = db.scalar(select(m.Membership).where(m.Membership.user_id == user.id))
    return {
        "token": token_for(user.id, member.org_id),
        "organization": serialize(db.get(m.Organization, member.org_id)),
    }


@app.get("/projects")
def projects(offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    return collection(db, m.Project, actor, offset, limit)


@app.post("/projects", status_code=201)
def create_project(body: CreateProject, actor=ACTOR, db=DB):
    require_write(actor)
    project = m.Project(org_id=actor.org_id, **body.model_dump())
    db.add(project)
    db.flush()
    audit(db, actor, "project_created", project.id)
    db.commit()
    return serialize(project)


@app.get("/agents")
def agents(offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    return collection(db, m.AgentRecord, actor, offset, limit)


@app.post("/agents", status_code=201)
async def create_agent(body: CreateAgent, actor=ACTOR, db=DB):
    require_write(actor)
    owned(db, m.Project, body.project_id, actor)
    available_tools(db, actor.org_id, body.connection_ids)
    agent = m.AgentRecord(
        org_id=actor.org_id,
        project_id=body.project_id,
        name="New agent",
        request=body.request,
        template=body.template or infer_template(body.request),
        no_data_reason=body.no_data_reason or "",
    )
    db.add(agent)
    db.flush()
    spec = await design(db, agent, body.connection_ids, model_backed=False)
    if body.minimum_score is not None:
        # The owner's decision about what is good enough; no builder role can change it.
        spec.quality_policy.minimum_score = body.minimum_score
    agent.name = spec.name
    version = persist_version(db, agent, spec)
    suite = seed_suite(db, agent)
    audit(db, actor, "agent_created", agent.id, {"no_data_stated": bool(agent.no_data_reason)})
    db.commit()
    return {**serialize(agent), "version": serialize(version), "suite_id": suite.id}


@app.get("/agents/{agent_id}")
def agent_detail(agent_id: str, actor=ACTOR, db=DB):
    agent = owned(db, m.AgentRecord, agent_id, actor)
    latest = db.scalar(
        select(m.AgentVersion).where(m.AgentVersion.agent_id == agent.id).order_by(m.AgentVersion.number.desc())
    )
    return {
        **serialize(agent),
        "truth_source": truth_source(db, agent),
        "held_out_uses": held_out_uses(db, agent),
        "latest_version": serialize(latest) if latest else None,
        "builds": collection(db, m.BuildJob, actor, predicates=(m.BuildJob.agent_id == agent.id,))["items"],
    }


@app.get("/agents/{agent_id}/versions")
def versions(agent_id: str, offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    owned(db, m.AgentRecord, agent_id, actor)
    return collection(db, m.AgentVersion, actor, offset, limit, (m.AgentVersion.agent_id == agent_id,))


@app.post("/agents/{agent_id}/versions", status_code=201)
def edit_spec(agent_id: str, body: AgentSpec, actor=ACTOR, db=DB):
    require_write(actor)
    agent = owned(db, m.AgentRecord, agent_id, actor)
    latest = db.scalar(
        select(m.AgentVersion).where(m.AgentVersion.agent_id == agent.id).order_by(m.AgentVersion.number.desc())
    )
    if body.quality_policy != AgentSpec.model_validate(latest.spec).quality_policy:
        require_admin(actor)
    body.design_metrics = AgentSpec.model_validate(latest.spec).design_metrics
    enforce_spec_scope(body, AgentSpec.model_validate(latest.spec), allow_policy_change=True)
    available_tools(db, actor.org_id, body.connection_ids)
    Draft202012Validator.check_schema(body.input_schema)
    Draft202012Validator.check_schema(body.output_schema)
    version = persist_version(db, agent, body, "User configuration revision; requires fresh evaluation")
    audit(db, actor, "agent_version_created", version.id)
    db.commit()
    return serialize(version)


NO_TRUTH_SOURCE = (
    "A build needs something to be judged against. Attach examples with correct answers, "
    "or state why this task can be checked without data."
)


def active_build(db, agent):
    return db.scalar(select(m.BuildJob).where(m.BuildJob.agent_id == agent.id, m.BuildJob.state.not_in(TERMINAL)))


@app.get("/agents/{agent_id}/datasets")
def datasets(agent_id: str, offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    owned(db, m.AgentRecord, agent_id, actor)
    return collection(db, m.Dataset, actor, offset, limit, (m.Dataset.agent_id == agent_id,))


@app.post("/agents/{agent_id}/datasets", status_code=201)
async def add_dataset(agent_id: str, body: AttachDataset, actor=ACTOR, db=DB):
    require_write(actor)
    agent = owned(db, m.AgentRecord, agent_id, actor)
    if active_build(db, agent):
        raise HTTPException(409, "Data cannot change while a build is running; cancel it or wait for it to finish")
    try:
        text = body.content if body.url is None else await fetch_dataset(body.url)
        records = parse_records(text, body.format)
        dataset, version = attach_dataset(
            db,
            agent,
            body.name,
            records,
            mapping=body.mapping.model_dump() if body.mapping else None,
            sizes={
                "development": body.development,
                "selection": body.development if body.selection is None else body.selection,
                "regression": body.regression,
                "validation": body.validation,
            },
            origin="upload" if body.url is None else "url",
            source_url=body.url or "",
        )
    except IntakeError as error:
        db.rollback()
        raise HTTPException(422, str(error)) from None
    except (TimeoutError, OSError):
        db.rollback()
        raise HTTPException(422, "The dataset address could not be reached") from None
    audit(db, actor, "dataset_attached", dataset.id, {"rows": dataset.rows, "splits": dataset.profile["splits"]})
    db.commit()
    return {**serialize(dataset), "version": serialize(version)}


@app.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, actor=ACTOR, db=DB):
    require_admin(actor)
    dataset = owned(db, m.Dataset, dataset_id, actor)
    agent = owned(db, m.AgentRecord, dataset.agent_id, actor)
    if active_build(db, agent):
        raise HTTPException(409, "Data cannot change while a build is running; cancel it or wait for it to finish")
    removed = remove_dataset(db, agent, dataset)
    audit(db, actor, "dataset_removed", dataset_id, removed)
    db.commit()
    return removed


def held_out_uses(db, agent):
    """How many times this agent's held-out cases have been scored. Each look makes them a little less held out."""
    return db.scalar(
        select(func.count(func.distinct(m.EvaluationResult.evaluation_run_id)))
        .join(m.EvaluationCase, m.EvaluationCase.id == m.EvaluationResult.case_id)
        .join(m.EvaluationSuite, m.EvaluationSuite.id == m.EvaluationCase.suite_id)
        .where(
            m.EvaluationSuite.agent_id == agent.id,
            m.EvaluationCase.org_id == agent.org_id,
            m.EvaluationCase.split == "validation",
        )
    )


def usage_by_role(records):
    roles = {}
    for record in records:
        row = roles.setdefault(
            record.role,
            {"calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "cost": 0.0, "unresolved": 0.0},
        )
        row["calls"] += 1
        row["input_tokens"] += record.input_tokens
        row["cached_tokens"] += record.cached_tokens
        row["output_tokens"] += record.output_tokens
        row["cost"] += record.cost
        row["unresolved"] += record.reserved_cost
    return roles


def document_summary(document):
    data = serialize(document)
    text = data.pop("text")
    return {**data, "excerpt": text[:600]}


@app.get("/agents/{agent_id}/context")
def context_documents(agent_id: str, offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    owned(db, m.AgentRecord, agent_id, actor)
    query = select(m.ContextDocument).where(
        m.ContextDocument.org_id == actor.org_id, m.ContextDocument.agent_id == agent_id
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(m.ContextDocument.created_at, m.ContextDocument.id).offset(offset).limit(limit))
    return {"items": [document_summary(row) for row in rows], "total": total, "offset": offset, "limit": limit}


@app.post("/agents/{agent_id}/context", status_code=201)
def add_context_document(agent_id: str, body: AddDocument, actor=ACTOR, db=DB):
    require_write(actor)
    agent = owned(db, m.AgentRecord, agent_id, actor)
    try:
        document = add_document(db, agent, body.name, body.text)
    except IntakeError as error:
        raise HTTPException(422, str(error)) from None
    audit(db, actor, "context_document_added", document.id, {"characters": document.chars})
    db.commit()
    return document_summary(document)


@app.get("/context/{document_id}")
def context_document(document_id: str, actor=ACTOR, db=DB):
    return serialize(owned(db, m.ContextDocument, document_id, actor))


@app.delete("/context/{document_id}", status_code=204)
def remove_context_document(document_id: str, actor=ACTOR, db=DB):
    require_write(actor)
    document = owned(db, m.ContextDocument, document_id, actor)
    audit(db, actor, "context_document_removed", document.id)
    db.delete(document)
    db.commit()


@app.get("/versions/compare")
def compare(left: str, right: str, actor=ACTOR, db=DB):
    a, b = owned(db, m.AgentVersion, left, actor), owned(db, m.AgentVersion, right, actor)
    if a.agent_id != b.agent_id:
        raise HTTPException(422, "Compare versions of the same agent")
    changes = [
        {"field": key, "before": a.spec.get(key), "after": b.spec.get(key)}
        for key in set(a.spec) | set(b.spec)
        if a.spec.get(key) != b.spec.get(key)
    ]
    return {
        "left": serialize(a),
        "right": serialize(b),
        "changes": changes,
        "evaluations": collection(
            db, m.EvaluationRun, actor, predicates=(m.EvaluationRun.version_id.in_([a.id, b.id]),)
        )["items"],
    }


@app.post("/agents/{agent_id}/builds", status_code=201)
def start_build(agent_id: str, body: Budget, actor=ACTOR, db=DB):
    require_write(actor)
    agent = owned(db, m.AgentRecord, agent_id, actor)
    if truth_source(db, agent) is None:
        raise HTTPException(422, NO_TRUTH_SOURCE)
    latest = db.scalar(
        select(m.AgentVersion).where(m.AgentVersion.agent_id == agent.id).order_by(m.AgentVersion.number.desc())
    )
    if mode_for(agent.template) != "live" and latest and not latest.spec.get("tools"):
        # Demo mode replays fixture tools. Every case of an agent without tools would fail unrun.
        raise HTTPException(
            422, "This agent works from the request alone, which needs a live model. This workspace is in demo mode."
        )
    job = new_job(db, agent, body)
    audit(db, actor, "build_started", job.id)
    db.commit()
    return serialize(job)


@app.get("/builds/{job_id}")
def build(job_id: str, actor=ACTOR, db=DB):
    job = owned(db, m.BuildJob, job_id, actor)
    usage = list(
        db.scalars(select(m.UsageRecord).where(m.UsageRecord.org_id == actor.org_id, m.UsageRecord.job_id == job.id))
    )
    return {
        **serialize(job),
        "factory_observed_cost": sum(record.cost for record in usage),
        "usage_by_role": usage_by_role(usage),
        "factory_reserved_cost": sum(record.reserved_cost for record in usage),
        "iterations": collection(db, m.BuildIteration, actor, predicates=(m.BuildIteration.job_id == job.id,))["items"],
    }


@app.post("/builds/{job_id}/redirect", status_code=201)
def redirect_build(job_id: str, body: RedirectBuild, actor=ACTOR, db=DB):
    require_write(actor)
    job = db.scalar(
        select(m.BuildJob).where(m.BuildJob.id == job_id, m.BuildJob.org_id == actor.org_id).with_for_update()
    )
    if not job:
        raise HTTPException(404, "Build not found")
    if job.state in TERMINAL:
        raise HTTPException(409, "Redirect requires an in-progress build")
    if job.iteration >= job.budget["max_iterations"]:
        raise HTTPException(409, "No evaluation iterations remain in this build budget")
    if job.checkpoint["version_id"] != body.expected_version_id:
        raise HTTPException(409, "Build candidate changed; refresh before redirecting")
    previous = owned(db, m.AgentVersion, body.expected_version_id, actor)
    previous_spec = AgentSpec.model_validate(previous.spec)
    if body.spec.quality_policy != previous_spec.quality_policy:
        require_admin(actor)
    body.spec.design_metrics = previous_spec.design_metrics
    enforce_spec_scope(body.spec, previous_spec, allow_policy_change=True)
    available_tools(db, actor.org_id, body.spec.connection_ids)
    Draft202012Validator.check_schema(body.spec.input_schema)
    Draft202012Validator.check_schema(body.spec.output_schema)
    agent = owned(db, m.AgentRecord, job.agent_id, actor)
    revised = persist_version(db, agent, body.spec, "User build redirection: " + body.reason)
    agent.request, agent.name = body.spec.purpose, body.spec.name
    history = [
        *job.checkpoint.get("redirections", []),
        {
            "from_version_id": previous.id,
            "version_id": revised.id,
            "reason": body.reason,
            "actor_id": actor.user_id,
            "at": now().isoformat(),
        },
    ]
    # Fresh evidence is required. Retain global iteration/cost/time budgets and all
    # historical evaluations, but do not compare a new objective to old scorecards.
    job.checkpoint = {"version_id": revised.id, "stagnation": 0, "redirections": history}
    job.state, job.error = "BUILDING", None
    job.lease_owner, job.lease_until = None, None
    emit(db, actor.org_id, "build_redirected", history[-1], job_id=job.id)
    audit(db, actor, "build_redirected", job.id, history[-1])
    db.commit()
    return {"build": serialize(job), "version": serialize(revised)}


@app.post("/builds/{job_id}/{action}")
def control_build(job_id: str, action: Literal["pause", "resume", "cancel"], actor=ACTOR, db=DB):
    require_write(actor)
    job = db.scalar(
        select(m.BuildJob).where(m.BuildJob.id == job_id, m.BuildJob.org_id == actor.org_id).with_for_update()
    )
    if not job:
        raise HTTPException(404, "Resource not found")
    control(db, job, action)
    audit(db, actor, "build_" + action, job.id)
    db.commit()
    return serialize(job)


@app.get("/builds/{job_id}/events")
async def build_events(job_id: str, request: Request, after: str | None = None, actor=ACTOR, db=DB):
    owned(db, m.BuildJob, job_id, actor)
    cursor = after or request.headers.get("last-event-id")

    async def stream():
        from factory.db import SessionLocal

        current = cursor
        while not await request.is_disconnected():
            with SessionLocal() as session:
                # Verify organization membership on every reconnect/poll, not just initial handshake.
                member = session.scalar(
                    select(m.Membership).where(
                        m.Membership.org_id == actor.org_id, m.Membership.user_id == actor.user_id
                    )
                )
                if not member:
                    return
                query = select(m.ExecutionEvent).where(
                    m.ExecutionEvent.org_id == actor.org_id, m.ExecutionEvent.job_id == job_id
                )
                if current:
                    previous = session.get(m.ExecutionEvent, current)
                    if previous and previous.org_id == actor.org_id and previous.job_id == job_id:
                        query = query.where(
                            (m.ExecutionEvent.created_at > previous.created_at)
                            | (
                                (m.ExecutionEvent.created_at == previous.created_at)
                                & (m.ExecutionEvent.id > previous.id)
                            )
                        )
                events = list(
                    session.scalars(query.order_by(m.ExecutionEvent.created_at, m.ExecutionEvent.id).limit(200))
                )
                for event in events:
                    current = event.id
                    yield f"id: {event.id}\ndata: {json.dumps(serialize(event))}\n\n"
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.get("/builds/{job_id}/history")
def build_history(job_id: str, offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    owned(db, m.BuildJob, job_id, actor)
    return collection(db, m.ExecutionEvent, actor, offset, limit, (m.ExecutionEvent.job_id == job_id,))


@app.post("/builds/{job_id}/test-proposals/accept")
def accept_test_proposals(job_id: str, body: TestDesign, actor=ACTOR, db=DB):
    from factory.builder import validate_test_design

    require_admin(actor)
    job = db.scalar(
        select(m.BuildJob).where(m.BuildJob.id == job_id, m.BuildJob.org_id == actor.org_id).with_for_update()
    )
    if not job:
        raise HTTPException(404, "Build not found")
    if job.state != "WAITING_FOR_APPROVAL" or not job.checkpoint.get("test_proposals"):
        raise HTTPException(409, "Build has no pending test proposal review")
    version = owned(db, m.AgentVersion, job.checkpoint["version_id"], actor)
    validate_test_design(db, version, body)
    reject_secret_config(body.model_dump())
    suite = db.scalar(
        select(m.EvaluationSuite).where(
            m.EvaluationSuite.agent_id == job.agent_id, m.EvaluationSuite.org_id == actor.org_id
        )
    )
    if not suite:
        raise HTTPException(409, "Agent has no evaluation suite")
    ids = []
    for authored in body.cases:
        case = m.EvaluationCase(
            org_id=actor.org_id, suite_id=suite.id, authorized_by=actor.user_id, **authored.model_dump()
        )
        db.add(case)
        db.flush()
        ids.append(case.id)
    job.checkpoint = {
        **job.checkpoint,
        "test_proposals": None,
        "accepted_case_ids": ids,
        "test_design_reviewed_by": actor.user_id,
        "test_design_reviewed_at": now().isoformat(),
        "waiting_reason": "",
    }
    control(db, job, "resume")
    audit(db, actor, "test_proposals_accepted", job.id, {"case_ids": ids})
    db.commit()
    return serialize(job)


@app.get("/integrations/catalog")
def integration_catalog(actor=ACTOR):
    return {
        "items": [
            {"kind": kind, "authentication": auth, "setup": setup}
            for kind, auth, setup in [
                ("fixture", "local", "Fictional isolated ERP"),
                ("rest", "bearer", "URL, approved hosts and operation schemas"),
                ("postgres", "encrypted DSN", "Read-only role and approved tables"),
                ("file", "upload", "CSV/XLSX with explicit model visibility"),
                ("webhook", "HMAC-SHA256", "Signed inbound events"),
                ("email", "IMAP/SMTP", "Credentials or clearly labeled mock provider"),
                ("mcp", "bearer", "Streamable HTTP with tool allowlist"),
            ]
        ]
    }


@app.get("/integrations")
def integrations(offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    return collection(db, m.Connection, actor, offset, limit)


def reject_secret_config(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEYS.search(key):
                raise HTTPException(422, "Credentials must be supplied in the encrypted secret field")
            reject_secret_config(item)
    elif isinstance(value, list):
        for item in value:
            reject_secret_config(item)


@app.post("/integrations", status_code=201)
async def create_integration(body: CreateConnection, actor=ACTOR, db=DB):
    require_admin(actor)
    reject_secret_config(body.config)
    connection = m.Connection(
        org_id=actor.org_id,
        name=body.name,
        kind=body.kind,
        config=body.config,
        encrypted_secret=encrypt(body.secret),
        permissions=body.permissions,
        status="setup_required",
    )
    db.add(connection)
    db.flush()
    if body.kind == "fixture":
        seed_business(db, actor.org_id)
        await discover_connection(db, connection)
    elif body.kind in ("file", "webhook") or (body.kind == "email" and body.config.get("provider") == "mock"):
        await discover_connection(db, connection)
    audit(db, actor, "integration_created", connection.id, {"kind": body.kind})
    db.commit()
    return serialize(connection)


@app.get("/integrations/{connection_id}")
async def integration_detail(connection_id: str, actor=ACTOR, db=DB):
    connection = owned(db, m.Connection, connection_id, actor)
    resources = list(db.scalars(select(m.DataSource).where(m.DataSource.connection_id == connection.id)))
    return {
        **serialize(connection),
        "tools": collection(db, m.ToolDefinition, actor, predicates=(m.ToolDefinition.connection_id == connection.id,))[
            "items"
        ],
        "data_sources": [serialize(source) for source in resources],
    }


@app.post("/integrations/{connection_id}/test")
async def test_connection(connection_id: str, actor=ACTOR, db=DB):
    require_admin(actor)
    connection = owned(db, m.Connection, connection_id, actor)
    if connection.status == "revoked":
        raise HTTPException(409, "Revoked connections cannot be tested")
    try:
        result = await discover_connection(db, connection)
    except Exception as error:
        connection.status = "setup_required"
        db.commit()
        return {
            "ok": False,
            "error_type": type(error).__name__,
            "message": "Connection failed; verify server-side configuration and credentials",
        }
    audit(db, actor, "integration_tested", connection.id)
    db.commit()
    return result


class DraftProposal(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    config: dict
    rationale: str = Field(default="", max_length=4000)
    samples: list[dict] = Field(default_factory=list, max_length=40)
    agent_id: str | None = None


class ImportOpenAPI(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    document: dict
    base_url: str | None = Field(default=None, max_length=2000)
    agent_id: str | None = None


class ApproveProposal(BaseModel):
    secret: str = Field(default="", max_length=20000)
    allow_write: bool = False
    # The administrator repeats the exact hosts: approving a host is a deliberate act, not a default.
    confirmed_hosts: list[str] = Field(max_length=10)
    attach: bool = True


@app.get("/connection-proposals")
def connection_proposals(offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    return collection(db, m.ConnectionProposal, actor, offset, limit)


@app.post("/connection-proposals", status_code=201)
def draft_connection_proposal(body: DraftProposal, actor=ACTOR, db=DB):
    require_write(actor)
    if body.agent_id:
        owned(db, m.AgentRecord, body.agent_id, actor)
    try:
        proposal = create_proposal(
            db, actor.org_id, body.name, body.config, body.rationale, body.samples, agent_id=body.agent_id
        )
    except ProposalError as error:
        raise HTTPException(422, str(error)) from None
    audit(db, actor, "connection_proposed", proposal.id, {"host": proposal.checks["host"]})
    db.commit()
    return serialize(proposal)


@app.post("/connection-proposals/import-openapi", status_code=201)
def import_openapi_proposal(body: ImportOpenAPI, actor=ACTOR, db=DB):
    require_write(actor)
    if body.agent_id:
        owned(db, m.AgentRecord, body.agent_id, actor)
    try:
        config, skipped = openapi_to_config(body.document, body.base_url)
        proposal = create_proposal(
            db,
            actor.org_id,
            body.name,
            config,
            "Imported from an OpenAPI document",
            agent_id=body.agent_id,
            origin="openapi",
        )
    except ProposalError as error:
        raise HTTPException(422, str(error)) from None
    proposal.checks = {**proposal.checks, "skipped": skipped[:60]}
    audit(db, actor, "connection_proposed", proposal.id, {"host": proposal.checks["host"], "origin": "openapi"})
    db.commit()
    return serialize(proposal)


@app.post("/connection-proposals/{proposal_id}/approve")
async def approve_connection_proposal(proposal_id: str, body: ApproveProposal, actor=ACTOR, db=DB):
    require_admin(actor)
    proposal = db.scalar(
        select(m.ConnectionProposal)
        .where(m.ConnectionProposal.id == proposal_id, m.ConnectionProposal.org_id == actor.org_id)
        .with_for_update()
    )
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    try:
        connection, version = await approve_proposal(
            db, actor, proposal, body.secret, body.allow_write, body.confirmed_hosts, body.attach
        )
    except ProposalError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from None
    except PermissionError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from None
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        # The vendor could not be reached or rejected the credential. Nothing is kept.
        db.rollback()
        raise HTTPException(502, f"The connection could not be activated ({type(error).__name__})") from None
    audit(
        db,
        actor,
        "connection_proposal_approved",
        proposal.id,
        {"connection_id": connection.id, "hosts": body.confirmed_hosts, "write": body.allow_write},
    )
    db.commit()
    return {
        "proposal": serialize(proposal),
        "connection": serialize(connection),
        "version": serialize(version) if version else None,
    }


@app.post("/connection-proposals/{proposal_id}/reject")
def reject_connection_proposal(proposal_id: str, actor=ACTOR, db=DB):
    require_admin(actor)
    proposal = owned(db, m.ConnectionProposal, proposal_id, actor)
    if proposal.status != "proposed":
        raise HTTPException(409, "This proposal has already been reviewed")
    proposal.status, proposal.reviewed_by, proposal.reviewed_at = "rejected", actor.user_id, now()
    audit(db, actor, "connection_proposal_rejected", proposal.id, {})
    db.commit()
    return serialize(proposal)


@app.post("/integrations/{connection_id}/revoke")
def revoke(connection_id: str, actor=ACTOR, db=DB):
    require_admin(actor)
    connection = db.scalar(
        select(m.Connection)
        .where(m.Connection.id == connection_id, m.Connection.org_id == actor.org_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not connection:
        raise HTTPException(404, "Connection not found")
    if connection.encrypted_secret:
        db.add(
            m.SecretRedactionEntry(
                org_id=actor.org_id, connection_id=connection.id, encrypted_secret=connection.encrypted_secret
            )
        )
    connection.status = "revoked"
    connection.encrypted_secret = ""
    audit(db, actor, "integration_revoked", connection.id)
    db.commit()
    return serialize(connection)


@app.post("/integrations/{connection_id}/import")
async def import_file(connection_id: str, file: UploadFile = File(...), actor=ACTOR, db=DB):
    require_admin(actor)
    connection = owned(db, m.Connection, connection_id, actor)
    if connection.kind != "file" or connection.status == "revoked":
        raise HTTPException(422, "Active file connection required")
    records = FileConnector.parse(await file.read(5_000_001), file.filename or "")
    source = m.DataSource(
        org_id=actor.org_id,
        connection_id=connection.id,
        name=file.filename or "Imported data",
        schema={"type": "object", "properties": {key: {} for key in (records[0] if records else {})}},
        records=records,
        model_visible=False,
    )
    db.add(source)
    db.flush()
    audit(db, actor, "data_imported", source.id, {"records": len(records), "model_visible": False})
    db.commit()
    return serialize(source)


class Visibility(BaseModel):
    model_visible: bool


@app.patch("/data-sources/{source_id}")
def data_visibility(source_id: str, body: Visibility, actor=ACTOR, db=DB):
    require_admin(actor)
    source = owned(db, m.DataSource, source_id, actor)
    source.model_visible = body.model_visible
    audit(db, actor, "data_visibility_changed", source.id, body.model_dump())
    db.commit()
    return serialize(source)


@app.post("/webhooks/{connection_id}")
async def inbound_webhook(connection_id: str, request: Request, db=DB):
    from factory.security import decrypt

    connection = db.get(m.Connection, connection_id)
    if (
        not connection
        or connection.kind != "webhook"
        or connection.status != "connected"
        or not connection.encrypted_secret
    ):
        raise HTTPException(404, "Webhook unavailable")
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(413, "Webhook body too large")
    timestamp = request.headers.get("X-Webhook-Timestamp", "")
    try:
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError("Expired signature")
    except ValueError:
        raise HTTPException(401, "Invalid webhook timestamp") from None
    expected = hmac.new(
        decrypt(connection.encrypted_secret).encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Webhook-Signature", "")):
        raise HTTPException(401, "Invalid webhook signature")
    payload = json.loads(body)
    validate(payload, connection.config.get("input_schema", {"type": "object"}))
    key = hashlib.sha256(timestamp.encode() + body).hexdigest()
    existing = db.scalar(
        select(m.BusinessRecord).where(
            m.BusinessRecord.org_id == connection.org_id,
            m.BusinessRecord.collection == "webhook:" + connection.id,
            m.BusinessRecord.key == key,
        )
    )
    if existing:
        return {"accepted": True, "duplicate": True}
    db.add(
        m.BusinessRecord(org_id=connection.org_id, collection="webhook:" + connection.id, key=key, data=redact(payload))
    )
    source = db.scalar(
        select(m.DataSource).where(m.DataSource.connection_id == connection.id, m.DataSource.name == "inbound_events")
    )
    if not source:
        source = m.DataSource(
            org_id=connection.org_id,
            connection_id=connection.id,
            name="inbound_events",
            schema=connection.config.get("input_schema", {}),
            records=[],
            model_visible=False,
        )
        db.add(source)
    source.records = [*source.records[-99:], redact(payload)]
    db.commit()
    return {"accepted": True, "duplicate": False}


@app.get("/agents/{agent_id}/suites")
def suites(agent_id: str, offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    owned(db, m.AgentRecord, agent_id, actor)
    return collection(db, m.EvaluationSuite, actor, offset, limit, (m.EvaluationSuite.agent_id == agent_id,))


@app.get("/suites/{suite_id}/cases")
def cases(suite_id: str, offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    owned(db, m.EvaluationSuite, suite_id, actor)
    return collection(db, m.EvaluationCase, actor, offset, limit, (m.EvaluationCase.suite_id == suite_id,))


@app.post("/suites/{suite_id}/cases", status_code=201)
def add_case(suite_id: str, body: CreateCase, actor=ACTOR, db=DB):
    require_write(actor)
    suite = owned(db, m.EvaluationSuite, suite_id, actor)
    reject_secret_config(body.input)
    reject_secret_config(body.environment.model_dump())
    if body.source != "replay" and body.environment.replay:
        raise HTTPException(422, "Recorded tool responses require replay source")
    for response in body.environment.replay:
        owned(db, m.ToolDefinition, response.tool_id, actor)
    for name in body.environment.state_overrides:
        if name not in fictional_data():
            raise HTTPException(422, "Unknown isolated-state collection")
    authorized_by = None
    if body.environment.data_mappings:
        require_admin(actor)
        version = db.scalar(
            select(m.AgentVersion)
            .where(m.AgentVersion.agent_id == suite.agent_id)
            .order_by(m.AgentVersion.number.desc())
        )
        for mapping in body.environment.data_mappings:
            source = owned(db, m.DataSource, mapping.source_id, actor)
            if not source.model_visible or not version or source.connection_id not in version.spec["connection_ids"]:
                raise HTTPException(403, "Mapped data requires explicit model visibility and an attached connection")
            check_connection(db, actor.org_id, source.connection_id)
            if mapping.collection not in fictional_data():
                raise HTTPException(422, "Unknown imported-state collection")
            if any(column not in source.schema.get("properties", {}) for column in mapping.fields.values()):
                raise HTTPException(422, "Mapping references an undiscovered field")
        authorized_by = actor.user_id
    if body.source == "live_read_only":
        require_admin(actor)
        if not body.environment.live_connection_ids or body.input.get("approve_in_test"):
            raise HTTPException(422, "Read-only evaluations need explicit connections and cannot request writes")
        version = db.scalar(
            select(m.AgentVersion)
            .where(m.AgentVersion.agent_id == suite.agent_id)
            .order_by(m.AgentVersion.number.desc())
        )
        for connection_id in body.environment.live_connection_ids:
            check_connection(db, actor.org_id, connection_id)
            if not version or connection_id not in version.spec["connection_ids"]:
                raise HTTPException(422, "Live connection is not attached to this agent")
        authorized_by = actor.user_id
    elif body.environment.live_connection_ids:
        raise HTTPException(422, "Live connections require explicitly authorized read-only source")
    case = m.EvaluationCase(org_id=actor.org_id, suite_id=suite_id, authorized_by=authorized_by, **body.model_dump())
    db.add(case)
    db.flush()
    audit(db, actor, "evaluation_case_created", case.id)
    db.commit()
    return serialize(case)


@app.post("/evaluation-results/{result_id}/review")
def review_result(result_id: str, body: HumanReview, actor=ACTOR, db=DB):
    from factory.evaluation import scorecard

    require_admin(actor)
    result = db.scalar(
        select(m.EvaluationResult)
        .where(m.EvaluationResult.id == result_id, m.EvaluationResult.org_id == actor.org_id)
        .with_for_update()
    )
    if not result:
        raise HTTPException(404, "Evaluation result not found")
    pending = [check for check in result.checks if check["category"] == "human_review" and check.get("pending")]
    if not pending:
        raise HTTPException(409, "Result has no pending human review")
    result.checks = [
        {
            **check,
            "passed": body.passed,
            "pending": False,
            "evidence": redact(body.evidence),
            "reviewed_by": actor.user_id,
            "reviewed_at": now().isoformat(),
        }
        if check["category"] == "human_review"
        else check
        for check in result.checks
    ]
    result.failures = [check["category"] for check in result.checks if not check["passed"]]
    result.passed = not result.failures
    evaluation = db.get(m.EvaluationRun, result.evaluation_run_id)
    db.flush()
    evaluation.scorecard = scorecard(db, evaluation)
    audit(db, actor, "evaluation_human_reviewed", result.id, {"passed": body.passed})
    db.commit()
    return serialize(result)


@app.post("/evaluation-results/{result_id}/grade")
async def retry_rubric_grade(result_id: str, actor=ACTOR, db=DB):
    from factory.evaluation import scorecard
    from factory.provider_accounting import BuildInterrupted
    from factory.qualitative import grade_rubric

    require_admin(actor)
    result = db.scalar(
        select(m.EvaluationResult).where(m.EvaluationResult.id == result_id, m.EvaluationResult.org_id == actor.org_id)
    )
    if not result:
        raise HTTPException(404, "Evaluation result not found")
    if not any(check["category"] == "qualitative" and check.get("pending") for check in result.checks):
        raise HTTPException(409, "Result has no pending rubric grading")
    case = owned(db, m.EvaluationCase, result.case_id, actor)
    run = owned(db, m.ExecutionRun, result.execution_id, actor)
    version = owned(db, m.AgentVersion, run.version_id, actor)
    evaluation = owned(db, m.EvaluationRun, result.evaluation_run_id, actor)
    jobs = list(
        db.scalars(
            select(m.BuildJob)
            .where(m.BuildJob.org_id == actor.org_id, m.BuildJob.agent_id == version.agent_id)
            .with_for_update()
        )
    )
    job = next((job for job in jobs if job.checkpoint.get("evaluation_id") == evaluation.id), None)
    remaining = max(0, job.budget["max_cost"] - job.spent) if job else version.spec["max_cost"]
    previous_cost = run.metrics.get("cost", 0)
    if job and "build_accounted_cost" not in run.metrics:
        # Existing completed result checkpoints already charged their observed cost.
        run.metrics = {**run.metrics, "build_accounted_cost": previous_cost}
    try:
        checks = await grade_rubric(
            db,
            version,
            run,
            case,
            max_cost=previous_cost + run.metrics.get("reserved_cost", 0) + remaining,
            job=job,
        )
    except BuildInterrupted:
        raise HTTPException(409, "Build changed during rubric grading; usage was retained") from None
    result = db.scalar(
        select(m.EvaluationResult)
        .where(m.EvaluationResult.id == result_id, m.EvaluationResult.org_id == actor.org_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not any(check["category"] == "qualitative" and check.get("pending") for check in result.checks):
        raise HTTPException(409, "Rubric grading was already resolved; usage was retained")
    result.checks = [check for check in result.checks if check["category"] != "qualitative"] + checks
    result.failures = [check["category"] for check in result.checks if not check["passed"]]
    result.passed = not result.failures
    db.flush()
    evaluation.scorecard = scorecard(db, evaluation)
    audit(db, actor, "evaluation_rubric_graded", result.id, {"pending": any(check.get("pending") for check in checks)})
    db.commit()
    return serialize(result)


@app.get("/agents/{agent_id}/evaluations")
def evaluations(agent_id: str, offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    owned(db, m.AgentRecord, agent_id, actor)
    version_ids = select(m.AgentVersion.id).where(m.AgentVersion.agent_id == agent_id)
    return collection(db, m.EvaluationRun, actor, offset, limit, (m.EvaluationRun.version_id.in_(version_ids),))


@app.get("/evaluations/{evaluation_id}")
def evaluation_detail(evaluation_id: str, actor=ACTOR, db=DB):
    evaluation = owned(db, m.EvaluationRun, evaluation_id, actor)
    return {
        **serialize(evaluation),
        "results": collection(
            db,
            m.EvaluationResult,
            actor,
            limit=200,
            predicates=(m.EvaluationResult.evaluation_run_id == evaluation.id,),
        )["items"],
    }


class EvaluationRequest(BaseModel):
    suite_id: str
    max_cost: float = Field(default=5, ge=0, le=1000)
    max_seconds: int = Field(default=1800, ge=1, le=86400)


@app.post("/versions/{version_id}/evaluate")
async def manual_evaluation(version_id: str, body: EvaluationRequest, actor=ACTOR, db=DB):
    from factory.evaluation import evaluate_suite

    require_write(actor)
    version = owned(db, m.AgentVersion, version_id, actor)
    suite = owned(db, m.EvaluationSuite, body.suite_id, actor)
    if suite.agent_id != version.agent_id:
        raise HTTPException(422, "Evaluation suite belongs to another agent")
    result = await evaluate_suite(db, version, suite, max_cost=body.max_cost, max_seconds=body.max_seconds)
    audit(db, actor, "evaluation_executed", result.id)
    db.commit()
    return serialize(result)


def quality_gate(db, version):
    policy = AgentSpec.model_validate(version.spec).quality_policy
    suites = list(db.scalars(select(m.EvaluationSuite).where(m.EvaluationSuite.agent_id == version.agent_id)))
    cases = list(db.scalars(select(m.EvaluationCase).where(m.EvaluationCase.suite_id.in_([s.id for s in suites]))))
    # Regression cases are the ones that must never break again; a suite drawn from sampled data may
    # have none yet. What can never be missing is evidence the builder did not see.
    if not cases or not {"development", "validation"}.issubset({c.split for c in cases}):
        raise HTTPException(409, "Separate development and held-out validation evidence is required")
    completed = select(m.EvaluationRun.id).where(
        m.EvaluationRun.version_id == version.id, m.EvaluationRun.status == "completed"
    )
    results = list(
        db.scalars(
            select(m.EvaluationResult)
            .where(m.EvaluationResult.evaluation_run_id.in_(completed))
            .order_by(m.EvaluationResult.created_at.desc())
        )
    )
    newest = {}
    for result in results:
        newest.setdefault((result.case_id, result.trial), result)
    required = [(case, trial) for case in cases for trial in range(case.trials)]
    if (
        len(cases) < policy.minimum_cases
        or sum(case.split == "validation" for case in cases) < policy.minimum_validation_cases
    ):
        raise HTTPException(409, "Insufficient distinct scenarios for the configured quality policy")
    if any((case.id, trial) not in newest for case, trial in required):
        raise HTTPException(409, "All current evaluation cases require completed evidence")
    selected = [newest[(case.id, trial)] for case, trial in required]
    if any(check.get("pending") for result in selected for check in result.checks):
        raise HTTPException(409, "Pending independent reviews or grading must be resolved")
    if sum(row.passed for row in selected) / len(selected) < policy.minimum_score or any(
        case.critical and not newest[(case.id, trial)].passed for case, trial in required
    ):
        raise HTTPException(409, "Candidate fails quality or critical regression gates")
    if any("safety" in row.failures or "approval_compliance" in row.failures for row in selected):
        raise HTTPException(409, "Candidate fails safety gates")
    runs = [db.get(m.ExecutionRun, result.execution_id) for result in selected]
    if (
        sum(run.metrics.get("duration_ms", 0) for run in runs) / len(runs) > policy.maximum_mean_latency_ms
        or sum(run.metrics.get("cost", 0) for run in runs) > policy.maximum_evaluation_cost
    ):
        raise HTTPException(409, "Candidate exceeds configured latency or cost gates")
    return {"score": sum(row.passed for row in selected) / len(selected), "cases": len(selected), "provisional": True}


class ApproveVersion(BaseModel):
    # Hashes of builder-written tool code the administrator has read and accepts.
    acknowledged_code: list[str] = Field(default_factory=list, max_length=20)


def unreviewed_generated_tools(db, version, acknowledged):
    """Generated tools whose exact code no administrator has approved for this agent before."""
    tools = version.spec.get("generated_tools") or []
    if not tools:
        return []
    reviewed = set(acknowledged)
    for earlier in db.scalars(
        select(m.AgentVersion).where(
            m.AgentVersion.agent_id == version.agent_id,
            m.AgentVersion.org_id == version.org_id,
            m.AgentVersion.approved_at.is_not(None),
        )
    ):
        reviewed.update(tool.get("code_hash") for tool in earlier.spec.get("generated_tools") or [])
    names = {
        tool.id: tool.name
        for tool in db.scalars(select(m.ToolDefinition).where(m.ToolDefinition.org_id == version.org_id))
    }
    return [
        {
            "name": tool["name"],
            "code_hash": tool["code_hash"],
            "capabilities": {alias: names.get(tool_id, tool_id) for alias, tool_id in tool["capabilities"].items()},
        }
        for tool in tools
        if tool["code_hash"] not in reviewed
    ]


@app.post("/versions/{version_id}/approve")
def approve_version(version_id: str, body: ApproveVersion | None = None, actor=ACTOR, db=DB):
    require_admin(actor)
    version = owned(db, m.AgentVersion, version_id, actor)
    gate = quality_gate(db, version)
    acknowledged = body.acknowledged_code if body else []
    pending = unreviewed_generated_tools(db, version, acknowledged)
    if pending:
        # Builder-written code is never approved implicitly: each new piece is acknowledged by its hash.
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "code_review_required",
                    "message": "This version contains builder-written tool code that must be reviewed and acknowledged",
                    "generated_tools": pending,
                }
            },
        )
    version.approved_at = now()
    version.approved_by = actor.user_id
    gate = {**gate, "acknowledged_code": sorted(set(acknowledged))} if acknowledged else gate
    audit(db, actor, "version_approved", version.id, gate)
    db.commit()
    return {**serialize(version), "quality_gate": gate}


class DeployRequest(BaseModel):
    version_id: str
    max_cost: float = Field(default=1, ge=0, le=100)
    lifetime_max_cost: float = Field(default=10, ge=0, le=10000)
    max_invocations: int = Field(default=1000, ge=1, le=100000)


class ShadowRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=20)
    max_cost: float = Field(default=1, ge=0, le=100)
    max_seconds: int = Field(default=120, ge=1, le=600)
    authorize_live_reads: bool = False


def gate_summary(db, version):
    try:
        return {"passed": True, **quality_gate(db, version)}
    except HTTPException as error:
        return {"passed": False, "reason": str(error.detail)}


@app.get("/versions/{version_id}/dossier")
def version_dossier(version_id: str, actor=ACTOR, db=DB):
    version = owned(db, m.AgentVersion, version_id, actor)
    return dossier(db, version, gate_summary(db, version))


@app.post("/versions/{version_id}/shadow")
async def shadow_version(version_id: str, body: ShadowRequest, actor=ACTOR, db=DB):
    require_admin(actor)
    version = owned(db, m.AgentVersion, version_id, actor)
    try:
        report = await shadow_run(
            db, actor, version, body.limit, body.max_cost, body.max_seconds, body.authorize_live_reads
        )
    except PermissionError as error:
        raise HTTPException(409, str(error)) from None
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    audit(db, actor, "shadow_comparison", version.id, {"compared": report["compared"]})
    db.commit()
    return report


@app.get("/agents/{agent_id}/feedback")
def agent_feedback(agent_id: str, actor=ACTOR, db=DB):
    agent = owned(db, m.AgentRecord, agent_id, actor)
    return {"items": feedback_candidates(db, agent)}


class CaseFromRun(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    split: Literal["development", "regression", "validation"] = "development"
    assertions: list[dict] = Field(min_length=1, max_length=50)
    critical: bool = False
    # Production input becomes test material only by an explicit, audited decision.
    authorize_data_use: bool = False


@app.post("/runs/{run_id}/case", status_code=201)
def case_from_run(run_id: str, body: CaseFromRun, actor=ACTOR, db=DB):
    require_admin(actor)
    run = owned(db, m.ExecutionRun, run_id, actor)
    if not body.authorize_data_use:
        raise HTTPException(422, "Using a real request as test material requires explicit authorization")
    version = owned(db, m.AgentVersion, run.version_id, actor)
    suite = db.scalar(
        select(m.EvaluationSuite).where(
            m.EvaluationSuite.agent_id == version.agent_id, m.EvaluationSuite.org_id == actor.org_id
        )
    )
    if not suite:
        raise HTTPException(409, "This agent has no evaluation suite yet")
    reject_secret_config(run.input)
    # The reviewer supplies the expected result; the agent's own output is never copied in as the answer.
    try:
        checked = CreateCase(
            name=body.name, split=body.split, input=run.input, assertions=body.assertions, critical=body.critical
        )
    except ValueError:
        raise HTTPException(422, "The assertions are not valid for an evaluation case") from None
    case = m.EvaluationCase(
        org_id=actor.org_id,
        suite_id=suite.id,
        name=checked.name,
        split=checked.split,
        source="production_input",
        input=run.input,
        assertions=checked.assertions,
        critical=checked.critical,
        authorized_by=actor.user_id,
    )
    db.add(case)
    db.flush()
    audit(db, actor, "evaluation_case_from_run", case.id, {"run_id": run.id, "split": case.split})
    db.commit()
    return serialize(case)


@app.get("/agents/{agent_id}/deployments")
def deployments(agent_id: str, offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    owned(db, m.AgentRecord, agent_id, actor)
    return collection(db, m.Deployment, actor, offset, limit, (m.Deployment.agent_id == agent_id,))


@app.post("/agents/{agent_id}/deployments", status_code=201)
def deploy(agent_id: str, body: DeployRequest, actor=ACTOR, db=DB):
    require_admin(actor)
    agent = owned(db, m.AgentRecord, agent_id, actor)
    version = owned(db, m.AgentVersion, body.version_id, actor)
    if version.agent_id != agent.id or not version.approved_at:
        raise HTTPException(409, "An approved version of this agent is required")
    quality_gate(db, version)
    for previous in db.scalars(
        select(m.Deployment).where(m.Deployment.agent_id == agent.id, m.Deployment.active.is_(True))
    ):
        previous.active = False
    deployment = m.Deployment(
        org_id=actor.org_id,
        agent_id=agent.id,
        version_id=version.id,
        policy={
            "max_cost": body.max_cost,
            "lifetime_max_cost": body.lifetime_max_cost,
            "max_invocations": body.max_invocations,
            "require_approval": True,
        },
    )
    db.add(deployment)
    db.flush()
    audit(db, actor, "agent_deployed", deployment.id, {"version_id": version.id})
    db.commit()
    return serialize(deployment)


@app.post("/deployments/{deployment_id}/pause")
def pause_deployment(deployment_id: str, actor=ACTOR, db=DB):
    require_admin(actor)
    deployment = owned(db, m.Deployment, deployment_id, actor)
    deployment.active = False
    audit(db, actor, "deployment_paused", deployment.id)
    db.commit()
    return serialize(deployment)


@app.post("/deployments/{deployment_id}/rollback", status_code=201)
def rollback(deployment_id: str, actor=ACTOR, db=DB):
    require_admin(actor)
    target = owned(db, m.Deployment, deployment_id, actor)
    return deploy(
        target.agent_id,
        DeployRequest(version_id=target.version_id, max_cost=target.policy.get("max_cost", 1)),
        actor,
        db,
    )


@app.post("/deployments/{deployment_id}/invoke")
async def invoke(deployment_id: str, body: Invoke, actor=ACTOR, db=DB):
    from factory.deployment_runtime import enqueue, execute_job

    run, job = enqueue(db, deployment_id, actor, body.input, body.idempotency_key)
    db.commit()
    if job and job.state in ("PENDING", "RUNNING"):
        completed = await execute_job(db, job.id)
        if completed:
            run = completed
    return serialize(run)


@app.get("/runs")
def runs(offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    return collection(db, m.ExecutionRun, actor, offset, limit)


@app.get("/runs/{run_id}")
def run_detail(run_id: str, actor=ACTOR, db=DB):
    run = owned(db, m.ExecutionRun, run_id, actor)
    events = list(
        db.scalars(
            select(m.ExecutionEvent)
            .where(m.ExecutionEvent.run_id == run.id)
            .order_by(m.ExecutionEvent.created_at, m.ExecutionEvent.id)
        )
    )
    return {**serialize(run), "events": [serialize(event) for event in events]}


@app.get("/approvals")
def approvals(offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    return collection(db, m.Approval, actor, offset, limit)


class ApprovalDecision(BaseModel):
    approved: bool


@app.post("/approvals/{approval_id}/resolve")
async def approval_decision(approval_id: str, body: ApprovalDecision, actor=ACTOR, db=DB):
    require_admin(actor)
    approval = db.scalar(
        select(m.Approval).where(m.Approval.id == approval_id, m.Approval.org_id == actor.org_id).with_for_update()
    )
    if not approval:
        raise HTTPException(404, "Resource not found")
    run = await resolve_approval(db, approval, actor, body.approved)
    audit(db, actor, "approval_resolved", approval.id, body.model_dump())
    db.commit()
    return serialize(run)


@app.get("/audit")
def audit_history(offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    return collection(db, m.AuditEvent, actor, offset, limit)


@app.get("/metrics")
def metrics(actor=ACTOR, db=DB):
    runs = list(db.scalars(select(m.ExecutionRun).where(m.ExecutionRun.org_id == actor.org_id)))
    evaluations = list(
        db.scalars(
            select(m.EvaluationRun)
            .where(m.EvaluationRun.org_id == actor.org_id, m.EvaluationRun.status == "completed")
            .order_by(m.EvaluationRun.created_at.desc())
            .limit(30)
        )
    )

    def count(cls, *where):
        return db.scalar(select(func.count()).select_from(cls).where(cls.org_id == actor.org_id, *where))

    return {
        "agents": count(m.AgentRecord),
        "deployed": count(m.Deployment, m.Deployment.active.is_(True)),
        "pending_approvals": count(m.Approval, m.Approval.status == "pending"),
        "runs": len(runs),
        "failure_rate": sum(r.status == "failed" for r in runs) / len(runs) if runs else 0,
        "cost": db.scalar(
            select(func.coalesce(func.sum(m.UsageRecord.cost), 0)).where(m.UsageRecord.org_id == actor.org_id)
        ),
        "reserved_cost": db.scalar(
            select(func.coalesce(func.sum(m.UsageRecord.reserved_cost), 0)).where(m.UsageRecord.org_id == actor.org_id)
        ),
        "mean_latency_ms": sum(r.metrics.get("duration_ms", 0) for r in runs) / len(runs) if runs else 0,
        "execution_mode": settings().execution_mode,
        "evaluations": [serialize(e) for e in evaluations],
    }


@app.get("/usage")
def usage_history(offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    return collection(db, m.UsageRecord, actor, offset, limit)


@app.get("/deployments/{deployment_id}/triggers")
def deployment_triggers(deployment_id: str, offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    owned(db, m.Deployment, deployment_id, actor)
    return collection(
        db, m.DeploymentTrigger, actor, offset, limit, (m.DeploymentTrigger.deployment_id == deployment_id,)
    )


@app.post("/deployments/{deployment_id}/triggers", status_code=201)
def create_deployment_trigger(deployment_id: str, body: CreateTrigger, actor=ACTOR, db=DB):
    require_admin(actor)
    deployment = owned(db, m.Deployment, deployment_id, actor)
    if not deployment.active:
        raise HTTPException(409, "Deployments must be active to configure triggers")
    version = owned(db, m.AgentVersion, deployment.version_id, actor)
    if body.kind == "schedule":
        if not body.interval_seconds:
            raise HTTPException(422, "Schedule interval is required")
        validate(body.input, version.spec["input_schema"])
    elif len(body.secret) < 20:
        raise HTTPException(422, "Webhook signing secret must have at least 20 characters")
    trigger = m.DeploymentTrigger(
        org_id=actor.org_id,
        deployment_id=deployment.id,
        actor_id=actor.user_id,
        name=body.name,
        kind=body.kind,
        input=redact(body.input),
        interval_seconds=body.interval_seconds if body.kind == "schedule" else None,
        next_run_at=now() + timedelta(seconds=body.interval_seconds) if body.kind == "schedule" else None,
        encrypted_secret=encrypt(body.secret) if body.kind == "webhook" else "",
    )
    db.add(trigger)
    db.flush()
    audit(db, actor, "deployment_trigger_created", trigger.id, {"kind": body.kind})
    db.commit()
    return serialize(trigger)


@app.patch("/deployment-triggers/{trigger_id}")
def update_deployment_trigger(trigger_id: str, body: TriggerUpdate, actor=ACTOR, db=DB):
    require_admin(actor)
    trigger = owned(db, m.DeploymentTrigger, trigger_id, actor)
    deployment = owned(db, m.Deployment, trigger.deployment_id, actor)
    if body.enabled and not deployment.active:
        raise HTTPException(409, "Deployment is paused")
    trigger.enabled = body.enabled
    if body.enabled:
        trigger.last_error = None
        if trigger.kind == "schedule":
            trigger.next_run_at = now() + timedelta(seconds=trigger.interval_seconds)
    audit(db, actor, "deployment_trigger_updated", trigger.id, body.model_dump())
    db.commit()
    return serialize(trigger)


@app.get("/deployments/{deployment_id}/invocations")
def deployment_invocations(deployment_id: str, offset: int = OFFSET, limit: int = LIMIT, actor=ACTOR, db=DB):
    owned(db, m.Deployment, deployment_id, actor)
    return collection(db, m.Invocation, actor, offset, limit, (m.Invocation.deployment_id == deployment_id,))


@app.post("/deployment-webhooks/{trigger_id}", status_code=202)
async def deployment_webhook(trigger_id: str, request: Request, db=DB):
    from factory.deployment_runtime import actor_for, enqueue
    from factory.security import decrypt

    trigger = db.get(m.DeploymentTrigger, trigger_id)
    if not trigger or trigger.kind != "webhook" or not trigger.enabled or not trigger.encrypted_secret:
        raise HTTPException(404, "Webhook unavailable")
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(413, "Webhook body too large")
    timestamp = request.headers.get("X-Webhook-Timestamp", "")
    try:
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError("Expired signature")
    except ValueError:
        raise HTTPException(401, "Invalid webhook timestamp") from None
    expected = hmac.new(
        decrypt(trigger.encrypted_secret).encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Webhook-Signature", "")):
        raise HTTPException(401, "Invalid webhook signature")
    payload = Invoke.model_validate_json(body)
    actor = actor_for(db, trigger.org_id, trigger.actor_id)
    key = "webhook:" + trigger.id + ":" + hashlib.sha256(payload.idempotency_key.encode()).hexdigest()
    run, job = enqueue(db, trigger.deployment_id, actor, payload.input, key)
    db.commit()
    return {"accepted": True, "run_id": run.id, "status": run.status}


@app.post("/approvals/{approval_id}/reconcile")
def reconcile_approval(approval_id: str, body: Reconciliation, actor=ACTOR, db=DB):
    require_admin(actor)
    approval = db.scalar(
        select(m.Approval).where(m.Approval.id == approval_id, m.Approval.org_id == actor.org_id).with_for_update()
    )
    if not approval:
        raise HTTPException(404, "Resource not found")
    if approval.status not in ("dispatching", "reconciliation_required"):
        raise HTTPException(409, "Only uncertain external dispatches can be reconciled")
    if approval.action.get("kind") != "connector":
        raise HTTPException(409, "External connector dispatch required")
    run = owned(db, m.ExecutionRun, approval.run_id, actor)
    if approval.status == "dispatching":
        from datetime import UTC, datetime

        version = owned(db, m.AgentVersion, run.version_id, actor)
        started = datetime.fromisoformat(approval.action.get("dispatch_started_at", approval.created_at.isoformat()))
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if (now() - started).total_seconds() < version.spec.get("timeout_seconds", 60) + 30:
            raise HTTPException(409, "Dispatch may still be in progress; wait for its timeout before reconciliation")
    approval.status = "reconciled_" + body.outcome
    approval.resolved_by = actor.user_id
    run.status = "completed" if body.outcome == "applied" else "cancelled"
    audit(db, actor, "external_dispatch_reconciled", approval.id, body.model_dump())
    emit(
        db,
        actor.org_id,
        "external_dispatch_reconciled",
        {
            "approval_id": approval.id,
            "outcome": body.outcome,
            "receipt": redact(body.receipt),
            "evidence_type": "human_provider_verification",
        },
        run_id=run.id,
    )
    db.commit()
    return serialize(run)
