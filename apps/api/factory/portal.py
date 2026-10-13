"""The customer side: a workspace of its own where a customer's documents arrive and are processed.

A customer workspace is an organization like any other, so its documents, page images, runs and
spend are isolated by tenant exactly as a builder's are. A builder opens one, installs a deployed
agent into it as an operation, and invites the customer's people with the customer role, which can
reach these endpoints and nothing else (security.principal). Nothing of the builder's workspace is
visible from here: an installed agent is a copy of one approved version.

Documents reach an operation by upload, from a mailbox that is checked for attachments, or posted
to an inbound address. Each is read (factory/reading.py), run through the operation's deployment by
the ordinary production queue, and kept with its page images and its answer. A person can correct
an answer; the agent's own answer is kept beside the correction.
"""

import asyncio
import hashlib
import json
import secrets
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile
from jsonschema import ValidationError, validate
from pydantic import Field
from sqlalchemy import func, select

from factory.db import get_db, now
from factory.deployment_runtime import actor_for, enqueue, execute_job
from factory.documents import MAX_FIELD_CHARS
from factory.http_transport import pinned_client
from factory.intake import IntakeError
from factory.mailbox import MailboxError, check_mailbox, mailbox_position
from factory.models import (
    AgentRecord,
    AgentVersion,
    Channel,
    Deployment,
    DocumentPage,
    ExportBatch,
    InboxDocument,
    Membership,
    Operation,
    OperationsRecord,
    Organization,
    Project,
    User,
)
from factory.operations import AREAS, view
from factory.payables import (
    EXPORT_FORMATS,
    QUICKBOOKS_BATCH,
    analytics,
    answer,
    check,
    export_file,
    insights,
    overview,
    price_gaps,
    reconcile,
    uncoded,
)
from factory.reading import MAX_IMAGE_BYTES, Reader, image_type
from factory.schemas import StrictModel
from factory.security import Principal, audit, decrypt, encrypt, owned, principal, redact_tenant, require_admin

router = APIRouter()
DB, ACTOR = Depends(get_db), Depends(principal)
OFFSET, LIMIT = Query(0, ge=0), Query(50, ge=1, le=200)
MAILBOX_INTERVAL = 120
MAILBOX_BATCH = 10
WEBHOOK_TIMEOUT = 15
# A price is called risen when it is more than this far above the last price paid for the item.
PRICE_RISE = Decimal("0.05")


def may_work(actor):
    """Uploading, correcting and connecting channels: the customer's people and the builder's, not viewers."""
    if actor.role not in ("admin", "editor", "customer"):
        raise HTTPException(403, "This account can view the workspace only")


def operation_of(db, actor, operation_id):
    return owned(db, Operation, operation_id, actor)


def page_parts(document):
    """A document's pages as stored. Older documents kept only the image hashes."""
    return [part if isinstance(part, dict) else {"page": part} for part in document.pages or []]


def page_ids(document):
    return [part["page"] for part in page_parts(document) if "page" in part]


def summary(document):
    values = {key: value for key, value in (answer(document) or {}).items() if not isinstance(value, (list, dict))}
    tables = {key: len(value) for key, value in (answer(document) or {}).items() if isinstance(value, list)}
    return {
        "id": document.id,
        "operation_id": document.operation_id,
        "name": document.name,
        "source": document.source,
        "sender": document.sender,
        "status": document.status,
        "error": document.error,
        "received_at": document.created_at,
        "stage": document.stage,
        "exceptions": len(document.exceptions or []),
        "reviewed": document.reviewed_at is not None,
        "corrected": document.corrected is not None,
        "pages": len(document.pages or []),
        "fields": values,
        "rows": tables,
    }


def detail(document):
    return {
        **summary(document),
        "page_ids": page_ids(document),
        "answer": answer(document),
        "agent_answer": document.output,
        "reviewed_at": document.reviewed_at,
        "run_id": document.run_id,
        "deliveries": document.deliveries or {},
        "exception_list": document.exceptions or [],
        "approved_at": document.approved_at,
        "approved_automatically": document.approved_at is not None and document.approved_by is None,
        "export_id": document.export_id,
    }


def processed(db, operation):
    return list(
        db.scalars(
            select(InboxDocument)
            .where(InboxDocument.operation_id == operation.id, InboxDocument.status == "processed")
            .order_by(InboxDocument.created_at)
            .limit(5000)
        )
    )


def assess(db, operation, document):
    """Run the automatic checks on a processed document and say where it stands.

    Something found: it waits for a person. Nothing found: it is ready, or approved outright when the
    customer has chosen to let clean documents through. A document a person has already approved or
    that has gone to the books keeps its place; only what the checks say about it is refreshed.
    """
    if operation.kind != "invoice":
        document.exceptions = []
        if document.stage in ("new", "review", "ready"):
            document.stage = "ready"
        return
    document.exceptions = check(document, processed(db, operation))
    if document.stage in ("approved", "exported"):
        return
    if document.exceptions:
        document.stage = "review"
    elif (operation.settings or {}).get("auto_approve_clean"):
        document.stage, document.approved_at, document.approved_by = "approved", now(), None
    else:
        document.stage = "ready"


# Taking a document in.


async def ingest(db, operation, data, name, source, sender="", channel_id=None):
    """Read one file, run it through the operation's agent and keep the result. Returns (document, new).

    The same file twice is one document. Failures are recorded on the document, not raised: a
    mailbox check must go on to the next attachment, and a person should see what went wrong.
    """
    if not operation.enabled:
        raise HTTPException(409, "This operation is paused")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(422, f"{name} is larger than {MAX_IMAGE_BYTES // 1_000_000} MB")
    if not (image_type(data) or data.lstrip()[:5] == b"%PDF-"):
        raise HTTPException(422, f"{name} is not a PDF, PNG or JPEG file")
    digest = hashlib.sha256(data).hexdigest()
    known = db.scalar(
        select(InboxDocument).where(InboxDocument.operation_id == operation.id, InboxDocument.content_hash == digest)
    )
    if known is not None and known.status != "failed":
        return known, False
    document = known or InboxDocument(
        org_id=operation.org_id,
        operation_id=operation.id,
        channel_id=channel_id,
        source=source,
        name=name[:300],
        sender=sender[:320],
        content_hash=digest,
    )
    document.status, document.error = "processing", None
    db.add(document)
    db.commit()
    deployment = db.get(Deployment, operation.deployment_id)
    version = db.get(AgentVersion, deployment.version_id)
    reader = Reader(db, operation.org_id)
    try:
        actor = actor_for(db, operation.org_id, operation.actor_id)
        text, parts = await reader.read(data, name, MAX_FIELD_CHARS, version.spec.get("reading"), keep="all")
        # Each page as it was taken in: its image, and its text where the page was typed. Kept whole so the
        # document can be put through the agent again without the file.
        document.pages = parts or []
        db.commit()
        run, job = enqueue(db, deployment.id, actor, {operation.document_field: text}, f"document-{document.id}")
        db.commit()
        if job and job.state in ("PENDING", "RUNNING"):
            run = await execute_job(db, job.id) or run
        document.run_id = run.id
        document.cost = reader.cost + float((run.metrics or {}).get("cost") or 0)
        if run.status == "completed" and isinstance(run.output, dict):
            document.output, document.status = run.output, "processed"
        else:
            document.status = "failed"
            document.error = f"The agent did not finish: {run.error or run.status}"[:500]
    except (IntakeError, PermissionError) as error:
        db.rollback()
        document.status, document.error = "failed", str(error)[:500]
    except HTTPException as error:
        db.rollback()
        document.status, document.error = "failed", str(error.detail)[:500]
    finally:
        await reader.close()
    document.cost = max(document.cost or 0, reader.cost)
    db.commit()
    if document.status == "processed":
        assess(db, operation, document)
        db.commit()
        if document.stage == "approved":
            await deliver(db, operation, document)
    return document, True


async def deliver(db, operation, document):
    """Post an approved result to each webhook channel. Once: a failed delivery is recorded, never retried
    here. Results go on when they are approved, not when they are read, so what leaves has been checked."""
    channels = db.scalars(
        select(Channel).where(Channel.operation_id == operation.id, Channel.kind == "webhook", Channel.enabled)
    )
    for channel in channels:
        url = channel.config.get("url", "")
        body = {
            "document_id": document.id,
            "operation": operation.name,
            "name": document.name,
            "received_at": document.created_at.isoformat(),
            "answer": answer(document),
        }
        try:
            # The pinned transport: every address the host resolves to is checked, and none may be private.
            async with pinned_client(url, [urlparse(url).hostname or ""], timeout=WEBHOOK_TIMEOUT) as client:
                headers = {"Content-Type": "application/json", "User-Agent": "AgentFactoryPortal/1.0"}
                if channel.encrypted_secret:
                    headers["Authorization"] = "Bearer " + decrypt(channel.encrypted_secret)
                response = await client.post(url, content=json.dumps(body, default=str), headers=headers)
            outcome = "delivered" if response.status_code < 300 else f"refused: HTTP {response.status_code}"
        except Exception as error:
            outcome = f"failed: {type(error).__name__}"
        document.deliveries = {**(document.deliveries or {}), channel.id: outcome}
    db.commit()


async def mailbox_tick(session_factory=None, fetch=check_mailbox):
    """Check the mailboxes that are due. Returns how many documents were taken in."""
    from factory.db import SessionLocal

    taken = 0
    with (session_factory or SessionLocal)() as db:
        due = list(
            db.scalars(
                select(Channel)
                .where(Channel.kind == "mailbox", Channel.enabled, Channel.next_check_at <= now())
                .order_by(Channel.next_check_at)
                .limit(5)
            )
        )
        for channel in due:
            # Claimed before the mailbox is opened, so a slow server is not checked twice at once.
            channel.next_check_at = now() + timedelta(seconds=MAILBOX_INTERVAL)
            db.commit()
            taken += await check_channel(db, channel, fetch)
    return taken


async def check_channel(db, channel, fetch=check_mailbox):
    operation = db.get(Operation, channel.operation_id)
    taken = 0
    try:
        password = decrypt(channel.encrypted_secret)
        position, files = await asyncio.to_thread(fetch, channel.config, password, channel.cursor or {}, MAILBOX_BATCH)
        problem = None
        for item in files:
            try:
                _, new = await ingest(
                    db, operation, item["data"], item["name"], "mailbox", sender=item["sender"], channel_id=channel.id
                )
                taken += new
            except HTTPException as error:
                # One attachment that cannot be taken in does not hold up the rest, or the mailbox.
                problem = f"{item['name']}: {error.detail}"
        channel.cursor, channel.last_error = position, problem[:300] if problem else None
    except MailboxError as error:
        channel.last_error = str(error)[:300]
    channel.last_checked_at = now()
    db.commit()
    return taken


# The portal's endpoints.


@router.get("/portal/me")
def portal_me(actor=ACTOR, db=DB):
    org = db.get(Organization, actor.org_id)
    operations = list(
        db.scalars(select(Operation).where(Operation.org_id == actor.org_id).order_by(Operation.created_at))
    )
    counts = dict(
        db.execute(
            select(InboxDocument.operation_id, func.count())
            .where(InboxDocument.org_id == actor.org_id)
            .group_by(InboxDocument.operation_id)
        ).all()
    )
    recorded = set(db.scalars(select(OperationsRecord.area).where(OperationsRecord.org_id == actor.org_id).distinct()))
    return {
        "email": db.get(User, actor.user_id).email,
        # The operations areas this workspace has records for, in the order the pages list them.
        "areas": [
            {"area": area, "title": title}
            for area, (title, _) in AREAS.items()
            if recorded and (area in recorded or area == "overview")
        ],
        "sample": bool(
            db.scalar(
                select(OperationsRecord.id)
                .where(OperationsRecord.org_id == actor.org_id, OperationsRecord.source == "sample")
                .limit(1)
            )
        ),
        "workspace": {"id": org.id, "name": org.name, "kind": org.kind},
        "role": actor.role,
        "can_work": actor.role in ("admin", "editor", "customer"),
        "operations": [
            {
                "id": operation.id,
                "name": operation.name,
                "enabled": operation.enabled,
                "kind": operation.kind,
                "documents": counts.get(operation.id, 0),
                "fields": output_fields(db, operation),
            }
            for operation in operations
        ],
    }


def output_fields(db, operation):
    """The answer's shape, for laying out tables: single fields, and the columns of each table."""
    deployment = db.get(Deployment, operation.deployment_id)
    schema = db.get(AgentVersion, deployment.version_id).spec.get("output_schema", {})
    single, tables = [], {}
    for field, shape in schema.get("properties", {}).items():
        if shape.get("type") == "array":
            tables[field] = list(shape.get("items", {}).get("properties", {}))
        else:
            single.append(field)
    return {"single": single, "tables": tables}


@router.get("/portal/operations/{operation_id}/documents")
def list_documents(
    operation_id: str,
    status: str | None = Query(default=None, pattern="^(processing|processed|failed)$"),
    stage: str | None = Query(default=None, pattern="^(review|ready|approved|exported)$"),
    offset: int = OFFSET,
    limit: int = LIMIT,
    actor=ACTOR,
    db=DB,
):
    operation = operation_of(db, actor, operation_id)
    query = select(InboxDocument).where(
        InboxDocument.org_id == actor.org_id, InboxDocument.operation_id == operation.id
    )
    if status:
        query = query.where(InboxDocument.status == status)
    if stage:
        query = query.where(InboxDocument.stage == stage, InboxDocument.status == "processed")
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(InboxDocument.created_at.desc(), InboxDocument.id).offset(offset).limit(limit))
    return {"items": [summary(row) for row in rows], "total": total, "offset": offset, "limit": limit}


@router.post("/portal/operations/{operation_id}/documents", status_code=201)
async def upload_document(operation_id: str, file: UploadFile = File(...), actor=ACTOR, db=DB):
    may_work(actor)
    operation = operation_of(db, actor, operation_id)
    data = await file.read(MAX_IMAGE_BYTES + 1)
    document, new = await ingest(db, operation, data, file.filename or "document", "upload")
    if new:
        audit(db, actor, "portal_document_uploaded", document.id, {"status": document.status})
        db.commit()
    return {**detail(document), "duplicate": not new}


@router.get("/portal/documents/{document_id}")
def get_document(document_id: str, actor=ACTOR, db=DB):
    return detail(owned(db, InboxDocument, document_id, actor))


class Review(StrictModel):
    # The whole answer as corrected, or nothing to leave the answer as it stands.
    corrected: dict | None = None
    # Approve the document: a person has looked, and whatever the checks raised is accepted.
    approve: bool = True


@router.post("/portal/documents/{document_id}/review")
async def review_document(document_id: str, body: Review, actor=ACTOR, db=DB):
    may_work(actor)
    document = owned(db, InboxDocument, document_id, actor)
    if document.status != "processed":
        raise HTTPException(409, "Only a processed document can be reviewed")
    if document.stage == "exported":
        raise HTTPException(409, "This document has gone to the books and can no longer be changed here")
    operation = db.get(Operation, document.operation_id)
    if body.corrected is not None:
        deployment = db.get(Deployment, operation.deployment_id)
        try:
            validate(body.corrected, db.get(AgentVersion, deployment.version_id).spec.get("output_schema", {}))
        except ValidationError as error:
            raise HTTPException(422, f"The correction does not fit the answer's shape: {error.message}"[:300]) from None
        # Filtered like anything else a person types in, and kept beside the agent's own answer.
        document.corrected = redact_tenant(db, actor.org_id, body.corrected)
        document.reviewed_at, document.reviewed_by = now(), actor.user_id
        if document.stage == "approved" and not body.approve:
            # Changed after approval and not approved again: it goes back to be looked at.
            document.stage, document.approved_at, document.approved_by = "review", None, None
    newly = body.approve and document.stage != "approved"
    if body.approve:
        document.stage, document.approved_at, document.approved_by = "approved", now(), actor.user_id
        document.reviewed_at, document.reviewed_by = now(), actor.user_id
    db.flush()
    # What the checks say is refreshed against the answer as it now stands.
    assess(db, operation, document)
    audit(
        db,
        actor,
        "portal_document_reviewed",
        document.id,
        {"corrected": body.corrected is not None, "approved": body.approve, "exceptions": len(document.exceptions)},
    )
    db.commit()
    if newly or (body.approve and body.corrected is not None):
        await deliver(db, operation, document)
    return detail(document)


async def reprocess(db, operation, document):
    """Run a document through the operation's agent again, from its stored page images.

    For a document that failed, and for every document after the agent behind an operation is
    replaced by a better one. Pages are read from what was kept; a page read before is not paid for
    again. A person's correction is left alone: the agent's answer is replaced beside it.
    """
    if not document.pages:
        raise HTTPException(409, "No page image was kept for this document, so it cannot be read again")
    deployment = db.get(Deployment, operation.deployment_id)
    version = db.get(AgentVersion, deployment.version_id)
    reader = Reader(db, operation.org_id)
    try:
        actor = actor_for(db, operation.org_id, operation.actor_id)
        parts = page_parts(document)
        if all("text" in part for part in parts):
            # Every page was typed: its text is on file, and nothing needs reading.
            text = "\n\n".join(part["text"] for part in parts)
        else:
            text = await reader.document(parts, version.spec.get("reading"), document.name)
        attempt = hashlib.sha256(f"{document.id}:{version.id}:{now().isoformat()}".encode()).hexdigest()[:24]
        run, job = enqueue(
            db, deployment.id, actor, {operation.document_field: text}, f"document-{document.id}-{attempt}"
        )
        db.commit()
        if job and job.state in ("PENDING", "RUNNING"):
            run = await execute_job(db, job.id) or run
        document.run_id = run.id
        document.cost = (document.cost or 0) + reader.cost + float((run.metrics or {}).get("cost") or 0)
        if run.status == "completed" and isinstance(run.output, dict):
            document.output, document.status, document.error = run.output, "processed", None
        else:
            document.status, document.error = "failed", f"The agent did not finish: {run.error or run.status}"[:500]
    except (IntakeError, PermissionError) as error:
        db.rollback()
        document.status, document.error = "failed", str(error)[:500]
    except HTTPException as error:
        db.rollback()
        document.status, document.error = "failed", str(error.detail)[:500]
    finally:
        await reader.close()
    if document.status == "processed":
        assess(db, operation, document)
    db.commit()
    return document


@router.post("/portal/documents/{document_id}/reprocess")
async def reprocess_document(document_id: str, actor=ACTOR, db=DB):
    may_work(actor)
    document = owned(db, InboxDocument, document_id, actor)
    if document.stage in ("approved", "exported"):
        raise HTTPException(409, "An approved document is not read again")
    document = await reprocess(db, db.get(Operation, document.operation_id), document)
    audit(db, actor, "portal_document_reprocessed", document.id, {"status": document.status})
    db.commit()
    return detail(document)


@router.post("/portal/operations/{operation_id}/recheck")
def recheck(operation_id: str, actor=ACTOR, db=DB):
    """Run the automatic checks again over every document not yet approved, oldest first."""
    may_work(actor)
    operation = operation_of(db, actor, operation_id)
    documents = processed(db, operation)
    for document in documents:
        assess(db, operation, document)
    db.commit()
    return {
        stage: sum(document.stage == stage for document in documents)
        for stage in ("review", "ready", "approved", "exported")
    }


@router.post("/portal/operations/{operation_id}/approve-ready")
async def approve_ready(operation_id: str, actor=ACTOR, db=DB):
    """Approve every document the checks found nothing wrong with. Those that need a person are left."""
    may_work(actor)
    operation = operation_of(db, actor, operation_id)
    ready = list(
        db.scalars(
            select(InboxDocument).where(InboxDocument.operation_id == operation.id, InboxDocument.stage == "ready")
        )
    )
    for document in ready:
        document.stage, document.approved_at, document.approved_by = "approved", now(), actor.user_id
    audit(db, actor, "portal_documents_approved", operation.id, {"documents": len(ready)})
    db.commit()
    for document in ready:
        await deliver(db, operation, document)
    return {"approved": len(ready)}


@router.get("/portal/pages/{content_hash}")
def get_page(content_hash: str, actor=ACTOR, db=DB):
    page = db.scalar(
        select(DocumentPage).where(DocumentPage.org_id == actor.org_id, DocumentPage.content_hash == content_hash)
    )
    if page is None:
        raise HTTPException(404, "Not found")
    return Response(
        content=bytes(page.data),
        media_type=page.mime,
        headers={"Cache-Control": "private, max-age=86400, immutable", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/portal/operations/{operation_id}/insights")
def get_insights(operation_id: str, actor=ACTOR, db=DB):
    operation = operation_of(db, actor, operation_id)
    documents = processed(db, operation)
    stages = {
        stage: sum(document.stage == stage for document in documents)
        for stage in ("review", "ready", "approved", "exported")
    }
    failed = db.scalar(
        select(func.count())
        .select_from(InboxDocument)
        .where(InboxDocument.operation_id == operation.id, InboxDocument.status == "failed")
    )
    return {**insights(documents), "price_gaps": price_gaps(documents), "stages": stages, "failed": failed}


@router.get("/portal/operations/{operation_id}/overview")
def get_overview(operation_id: str, actor=ACTOR, db=DB):
    """What this work has added up to, for the owner: volumes, what needed nobody, what was caught."""
    operation = operation_of(db, actor, operation_id)
    documents = processed(db, operation)
    checked = []
    for other in db.scalars(select(Operation).where(Operation.org_id == actor.org_id, Operation.kind == "statement")):
        checked += [reconcile(statement, documents) for statement in processed(db, other)]
    failed = db.scalar(
        select(func.count())
        .select_from(InboxDocument)
        .where(InboxDocument.operation_id == operation.id, InboxDocument.status == "failed")
    )
    return {**overview(documents, checked), "failed": failed, "operation": operation.name}


@router.get("/portal/areas/{area}")
def get_area(
    area: str,
    location: str | None = Query(None, max_length=200),
    weeks: int = Query(8, ge=1, le=52),
    actor=ACTOR,
    db=DB,
):
    """One operations area for this workspace, worked out from its records."""
    if area not in AREAS:
        raise HTTPException(404, "Not found")
    rows = list(db.scalars(select(OperationsRecord).where(OperationsRecord.org_id == actor.org_id).limit(50000)))
    if not rows:
        raise HTTPException(404, "This workspace has no operations records")
    return view(area, rows, location, weeks)


@router.get("/portal/analytics")
def get_analytics(place: str | None = Query(None, max_length=300), actor=ACTOR, db=DB):
    """The dashboard: what was bought across every invoice agent in this workspace, and where each agent stands."""
    operations = list(
        db.scalars(select(Operation).where(Operation.org_id == actor.org_id).order_by(Operation.created_at))
    )
    documents, agents = [], []
    for operation in operations:
        held = processed(db, operation)
        if operation.kind == "invoice":
            documents += held
        failed = db.scalar(
            select(func.count())
            .select_from(InboxDocument)
            .where(InboxDocument.operation_id == operation.id, InboxDocument.status == "failed")
        )
        agents.append(
            {
                "id": operation.id,
                "name": operation.name,
                "kind": operation.kind,
                "enabled": operation.enabled,
                "documents": len(held),
                "review": sum(document.stage == "review" for document in held) if operation.kind == "invoice" else 0,
                "ready": sum(document.stage == "ready" for document in held) if operation.kind == "invoice" else 0,
                "failed": failed,
            }
        )
    return {**analytics(documents, place), "agents": agents}


@router.get("/portal/operations/{operation_id}/export.csv")
def export_csv(operation_id: str, actor=ACTOR, db=DB):
    """Every line of every processed document, whatever its stage. For looking at, not for the books."""
    operation = operation_of(db, actor, operation_id)
    return Response(
        content=export_file("lines", processed(db, operation), operation.settings or {}), media_type="text/csv"
    )


# Settings, the books, and statements.


class Account(StrictModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=200)


class OperationSettings(StrictModel):
    # Approve documents the checks find nothing wrong with, without a person.
    auto_approve_clean: bool = False
    # Days from the invoice date to the due date written on a bill.
    terms_days: int = Field(default=30, ge=0, le=365)
    # The ledger accounts lines can be coded to, the account for anything not otherwise coded, and
    # the account for each supplier that has one of its own.
    accounts: list[Account] = Field(default_factory=list, max_length=500)
    default_account: str = Field(default="", max_length=40)
    supplier_accounts: dict[str, str] = Field(default_factory=dict)
    tax_code: str = Field(default="", max_length=60)


def settings_view(db, operation):
    settings = OperationSettings.model_validate(operation.settings or {}).model_dump()
    documents = processed(db, operation)
    suppliers = sorted({str((answer(document) or {}).get("supplier") or "") for document in documents} - {""})
    return {**settings, "suppliers": suppliers, "formats": EXPORT_FORMATS}


@router.get("/portal/operations/{operation_id}/settings")
def get_settings(operation_id: str, actor=ACTOR, db=DB):
    return settings_view(db, operation_of(db, actor, operation_id))


@router.put("/portal/operations/{operation_id}/settings")
def put_settings(operation_id: str, body: OperationSettings, actor=ACTOR, db=DB):
    may_work(actor)
    operation = operation_of(db, actor, operation_id)
    codes = {account.code for account in body.accounts}
    used = {body.default_account, *body.supplier_accounts.values()} - {""}
    if codes and used - codes:
        raise HTTPException(
            422, "An account is used that is not in the list of accounts: " + ", ".join(sorted(used - codes))
        )
    operation.settings = body.model_dump()
    audit(db, actor, "portal_settings_changed", operation.id, {"auto_approve_clean": body.auto_approve_clean})
    db.commit()
    return settings_view(db, operation)


class CreateExport(StrictModel):
    format: str = Field(pattern="^(xero|quickbooks|lines)$")


def export_view(batch):
    return {
        "id": batch.id,
        "format": batch.format,
        "format_name": EXPORT_FORMATS[batch.format],
        "documents": batch.documents,
        "created_at": batch.created_at,
    }


@router.get("/portal/operations/{operation_id}/exports")
def list_exports(operation_id: str, actor=ACTOR, db=DB):
    operation = operation_of(db, actor, operation_id)
    rows = db.scalars(
        select(ExportBatch)
        .where(ExportBatch.operation_id == operation.id)
        .order_by(ExportBatch.created_at.desc())
        .limit(100)
    )
    waiting = [document for document in processed(db, operation) if document.stage == "approved"]
    return {
        "items": [export_view(row) for row in rows],
        "waiting": len(waiting),
        "uncoded_suppliers": uncoded(operation.settings or {}, waiting),
    }


@router.post("/portal/operations/{operation_id}/exports", status_code=201)
def create_export(operation_id: str, body: CreateExport, actor=ACTOR, db=DB):
    """Send the approved documents to the books: one file, and each document marked as gone.

    A document goes once. The file is kept, so the same batch can be fetched again unchanged.
    """
    may_work(actor)
    operation = operation_of(db, actor, operation_id)
    settings = operation.settings or {}
    waiting = [document for document in processed(db, operation) if document.stage == "approved"]
    if not waiting:
        raise HTTPException(409, "No approved documents are waiting to be sent")
    if body.format != "lines" and uncoded(settings, waiting):
        raise HTTPException(
            422,
            "Choose a ledger account before sending to the books: none is set for "
            + ", ".join(uncoded(settings, waiting)),
        )
    if body.format == "quickbooks":
        waiting = waiting[:QUICKBOOKS_BATCH]
    batch = ExportBatch(
        org_id=actor.org_id,
        operation_id=operation.id,
        format=body.format,
        created_by=actor.user_id,
        documents=len(waiting),
        content=export_file(body.format, waiting, settings),
    )
    db.add(batch)
    db.flush()
    for document in waiting:
        document.stage, document.export_id = "exported", batch.id
    audit(db, actor, "portal_export_created", batch.id, {"format": body.format, "documents": len(waiting)})
    db.commit()
    return export_view(batch)


@router.get("/portal/exports/{export_id}/file")
def export_content(export_id: str, actor=ACTOR, db=DB):
    batch = owned(db, ExportBatch, export_id, actor)
    return Response(content=batch.content, media_type="text/csv")


@router.get("/portal/documents/{document_id}/reconciliation")
def reconciliation(document_id: str, actor=ACTOR, db=DB):
    """A supplier's statement against the invoices this workspace has received."""
    document = owned(db, InboxDocument, document_id, actor)
    operation = db.get(Operation, document.operation_id)
    if operation.kind != "statement" or document.status != "processed":
        raise HTTPException(404, "Not found")
    invoices = []
    for other in db.scalars(select(Operation).where(Operation.org_id == actor.org_id, Operation.kind == "invoice")):
        invoices += processed(db, other)
    return reconcile(document, invoices)


# Channels.


def channel_view(channel):
    return {
        "id": channel.id,
        "operation_id": channel.operation_id,
        "kind": channel.kind,
        "name": channel.name,
        "enabled": channel.enabled,
        "config": channel.config,
        "last_checked_at": channel.last_checked_at,
        "last_error": channel.last_error,
        "has_secret": bool(channel.encrypted_secret),
    }


class CreateChannel(StrictModel):
    kind: str = Field(pattern="^(mailbox|inbound|webhook)$")
    name: str = Field(min_length=1, max_length=200)
    # mailbox: the IMAP server, the account and its password. webhook: the https address, and an optional bearer key.
    host: str | None = Field(default=None, min_length=3, max_length=253)
    username: str | None = Field(default=None, min_length=1, max_length=320)
    password: str | None = Field(default=None, min_length=1, max_length=500)
    folder: str = Field(default="INBOX", min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=9, max_length=2000)
    key: str | None = Field(default=None, min_length=1, max_length=500)


@router.get("/portal/operations/{operation_id}/channels")
def list_channels(operation_id: str, actor=ACTOR, db=DB):
    operation = operation_of(db, actor, operation_id)
    rows = db.scalars(select(Channel).where(Channel.operation_id == operation.id).order_by(Channel.created_at))
    return {"items": [channel_view(row) for row in rows]}


@router.post("/portal/operations/{operation_id}/channels", status_code=201)
async def create_channel(operation_id: str, body: CreateChannel, actor=ACTOR, db=DB):
    may_work(actor)
    operation = operation_of(db, actor, operation_id)
    channel = Channel(org_id=actor.org_id, operation_id=operation.id, kind=body.kind, name=body.name)
    issued = None
    if body.kind == "mailbox":
        if not (body.host and body.username and body.password):
            raise HTTPException(422, "A mailbox needs its IMAP server, the account name and its password")
        channel.config = {"host": body.host.strip().lower(), "username": body.username, "folder": body.folder}
        try:
            # Opening it proves the details work, and finds where the mailbox stands now: only mail that
            # arrives after this is taken in, never the mailbox's history.
            channel.cursor = await asyncio.to_thread(mailbox_position, channel.config, body.password)
        except MailboxError as error:
            raise HTTPException(422, str(error)) from None
        channel.encrypted_secret = encrypt(body.password)
        channel.next_check_at = now()
    elif body.kind == "webhook":
        parsed = urlparse(body.url or "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(422, "Results can be sent to a credential-free https address only")
        channel.config = {"url": body.url}
        channel.encrypted_secret = encrypt(body.key) if body.key else ""
    else:
        # Shown once. Only its hash is kept.
        issued = secrets.token_urlsafe(32)
        channel.token_hash = hashlib.sha256(issued.encode()).hexdigest()
        channel.config = {}
    db.add(channel)
    db.flush()
    audit(db, actor, "portal_channel_created", channel.id, {"kind": channel.kind})
    db.commit()
    return {**channel_view(channel), **({"key": issued, "address": f"/portal/inbound/{channel.id}"} if issued else {})}


class ChannelUpdate(StrictModel):
    enabled: bool


@router.patch("/portal/channels/{channel_id}")
def update_channel(channel_id: str, body: ChannelUpdate, actor=ACTOR, db=DB):
    may_work(actor)
    channel = owned(db, Channel, channel_id, actor)
    channel.enabled = body.enabled
    if body.enabled and channel.kind == "mailbox":
        channel.next_check_at = now()
    audit(db, actor, "portal_channel_updated", channel.id, {"enabled": body.enabled})
    db.commit()
    return channel_view(channel)


@router.delete("/portal/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: str, actor=ACTOR, db=DB):
    may_work(actor)
    channel = owned(db, Channel, channel_id, actor)
    db.delete(channel)
    audit(db, actor, "portal_channel_removed", channel_id, {"kind": channel.kind})
    db.commit()
    return Response(status_code=204)


@router.post("/portal/channels/{channel_id}/check")
async def check_now(channel_id: str, actor=ACTOR, db=DB):
    may_work(actor)
    channel = owned(db, Channel, channel_id, actor)
    if channel.kind != "mailbox":
        raise HTTPException(422, "Only a mailbox can be checked")
    taken = await check_channel(db, channel)
    return {**channel_view(channel), "taken_in": taken}


@router.post("/portal/inbound/{channel_id}", status_code=201)
async def inbound(
    channel_id: str,
    file: UploadFile = File(...),
    sender: str = Form(default="", max_length=320),
    authorization: str = Header(default=""),
    db=DB,
):
    """Where another system posts a file. Authorised by the channel's key alone: there is no signed-in person."""
    channel = db.get(Channel, channel_id)
    given = authorization.removeprefix("Bearer ").strip()
    expected = channel.token_hash if channel and channel.kind == "inbound" and channel.enabled else None
    if not expected or not given or not secrets.compare_digest(hashlib.sha256(given.encode()).hexdigest(), expected):
        raise HTTPException(404, "Not found")
    operation = db.get(Operation, channel.operation_id)
    data = await file.read(MAX_IMAGE_BYTES + 1)
    document, new = await ingest(
        db, operation, data, file.filename or "document", "inbound", sender=sender, channel_id=channel.id
    )
    return {"id": document.id, "status": document.status, "duplicate": not new}


# The builder's side of it: opening a customer's workspace and putting an agent to work there.


class CreateCustomer(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class InstallOperation(StrictModel):
    deployment_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=200)
    lifetime_max_cost: float = Field(default=50, ge=0, le=100000)
    max_invocations: int = Field(default=10000, ge=1, le=10_000_000)


def operation_kind(spec):
    """What an agent's documents are, from the shape of its answer: a statement lists invoices by number
    and amount and has no invoice number of its own; anything else is treated as an invoice."""
    properties = spec.get("output_schema", {}).get("properties", {})
    for shape in properties.values():
        rows = shape.get("items", {}).get("properties", {}) if shape.get("type") == "array" else {}
        if "invoice_number" in rows and "amount" in rows and "invoice_number" not in properties:
            return "statement"
    return "invoice"


def customer_org(db, actor, org_id):
    """A customer workspace this builder opened and still administers."""
    require_admin(actor)
    org = db.get(Organization, org_id)
    member = db.scalar(select(Membership).where(Membership.org_id == org_id, Membership.user_id == actor.user_id))
    if not org or org.kind != "customer" or org.parent_org_id != actor.org_id or not member or member.role != "admin":
        raise HTTPException(404, "Resource not found")
    return org


def customer_view(db, org):
    operations = list(db.scalars(select(Operation).where(Operation.org_id == org.id).order_by(Operation.created_at)))
    documents, cost = db.execute(
        select(func.count(), func.coalesce(func.sum(InboxDocument.cost), 0)).where(InboxDocument.org_id == org.id)
    ).one()
    members = db.scalar(
        select(func.count()).select_from(Membership).where(Membership.org_id == org.id, Membership.role == "customer")
    )
    return {
        "id": org.id,
        "name": org.name,
        "created_at": org.created_at,
        "operations": [
            {"id": item.id, "name": item.name, "enabled": item.enabled, "kind": item.kind, "source": item.source}
            for item in operations
        ],
        "documents": documents,
        "cost": float(cost),
        "customer_members": members,
    }


@router.get("/customers")
def customers(actor=ACTOR, db=DB):
    require_admin(actor)
    rows = db.scalars(
        select(Organization)
        .join(Membership, Membership.org_id == Organization.id)
        .where(
            Organization.kind == "customer",
            Organization.parent_org_id == actor.org_id,
            Membership.user_id == actor.user_id,
            Membership.role == "admin",
        )
        .order_by(Organization.created_at)
    )
    return {"items": [customer_view(db, org) for org in rows]}


@router.get("/customers/installable")
def installable(actor=ACTOR, db=DB):
    """The deployments of this workspace that can be put to work for a customer: active, approved, and
    taking one document as their whole request."""
    require_admin(actor)
    found = []
    for deployment in db.scalars(
        select(Deployment)
        .where(Deployment.org_id == actor.org_id, Deployment.active)
        .order_by(Deployment.created_at.desc())
    ):
        version, agent = db.get(AgentVersion, deployment.version_id), db.get(AgentRecord, deployment.agent_id)
        spec = version.spec
        properties = spec.get("input_schema", {}).get("properties", {})
        if (
            version.approved_at
            and not (spec.get("tools") or spec.get("connection_ids") or spec.get("generated_tools"))
            and len(properties) == 1
            and next(iter(properties.values())).get("type") == "string"
        ):
            found.append(
                {
                    "deployment_id": deployment.id,
                    "agent_id": agent.id,
                    "agent": agent.name,
                    "version": version.number,
                    "deployed_at": deployment.created_at,
                }
            )
    return {"items": found}


@router.post("/customers", status_code=201)
def create_customer(body: CreateCustomer, actor=ACTOR, db=DB):
    require_admin(actor)
    if db.get(Organization, actor.org_id).kind != "builder":
        raise HTTPException(409, "A customer workspace cannot open another")
    org = Organization(name=body.name, kind="customer", parent_org_id=actor.org_id)
    db.add(org)
    db.flush()
    # The builder administers the workspace it opened. The customer's people are invited into it.
    db.add(Membership(org_id=org.id, user_id=actor.user_id, role="admin"))
    db.add(Project(org_id=org.id, name="Operations", description="Agents working for this customer"))
    audit(db, actor, "customer_workspace_opened", org.id, {"name": body.name})
    audit(db, Principal(actor.user_id, org.id, "admin"), "workspace_opened_by_builder", org.id)
    db.commit()
    return customer_view(db, org)


@router.post("/customers/{org_id}/operations", status_code=201)
def install_operation(org_id: str, body: InstallOperation, actor=ACTOR, db=DB):
    """Put a deployed agent to work in a customer's workspace, as a copy of its approved version.

    The copy carries the version exactly as approved here, where it was measured. The customer
    workspace gets its own deployment with its own spending limits, and none of this workspace's
    examples, cases or evaluations.
    """
    org = customer_org(db, actor, org_id)
    deployment = owned(db, Deployment, body.deployment_id, actor)
    version = db.get(AgentVersion, deployment.version_id)
    agent = db.get(AgentRecord, deployment.agent_id)
    if not deployment.active or not version.approved_at or version.org_id != actor.org_id:
        raise HTTPException(409, "Only an active deployment of an approved version can be installed")
    spec = version.spec
    if spec.get("tools") or spec.get("connection_ids") or spec.get("generated_tools"):
        raise HTTPException(422, "An agent that uses connections or tools cannot be installed for a customer yet")
    properties = spec.get("input_schema", {}).get("properties", {})
    if len(properties) != 1 or next(iter(properties.values())).get("type") != "string":
        raise HTTPException(422, "Only an agent whose request is one document can be installed for a customer")
    there = Principal(actor.user_id, org.id, "admin")
    project = db.scalar(select(Project).where(Project.org_id == org.id).order_by(Project.created_at))
    copy = AgentRecord(
        org_id=org.id, project_id=project.id, name=agent.name, request=agent.request, template=agent.template
    )
    db.add(copy)
    db.flush()
    installed = AgentVersion(
        org_id=org.id,
        agent_id=copy.id,
        number=1,
        spec=spec,
        hypothesis=f"Installed from version {version.number} of {agent.name}"[:1000],
        approved_at=now(),
        approved_by=actor.user_id,
    )
    db.add(installed)
    db.flush()
    copy.best_version_id = installed.id
    placed = Deployment(
        org_id=org.id,
        agent_id=copy.id,
        version_id=installed.id,
        policy={
            "max_cost": deployment.policy.get("max_cost", 1),
            "lifetime_max_cost": body.lifetime_max_cost,
            "max_invocations": body.max_invocations,
            "require_approval": True,
        },
    )
    db.add(placed)
    db.flush()
    operation = Operation(
        org_id=org.id,
        deployment_id=placed.id,
        actor_id=actor.user_id,
        name=body.name,
        document_field=next(iter(properties)),
        kind=operation_kind(spec),
        source={"org_id": actor.org_id, "agent_id": agent.id, "version_id": version.id, "version": version.number},
    )
    db.add(operation)
    db.flush()
    audit(db, actor, "operation_installed_for_customer", operation.id, {"customer": org.id, "version_id": version.id})
    audit(db, there, "operation_installed", operation.id, {"name": body.name})
    db.commit()
    return customer_view(db, org)


class UpgradeOperation(StrictModel):
    deployment_id: str = Field(min_length=36, max_length=36)
    # Read again every document that no person has approved yet, with the new version.
    reprocess: bool = True


@router.post("/customers/{org_id}/operations/{operation_id}/upgrade")
async def upgrade_operation(org_id: str, operation_id: str, body: UpgradeOperation, actor=ACTOR, db=DB):
    """Replace the agent behind a customer's operation with a newer approved version of the builder's.

    The new version is copied in as the next version of the customer's agent and gets a deployment
    of its own with the same limits; the old one is switched off, not removed, so what it produced
    still points at the version that produced it.
    """
    org = customer_org(db, actor, org_id)
    operation = db.get(Operation, operation_id)
    if not operation or operation.org_id != org.id:
        raise HTTPException(404, "Resource not found")
    deployment = owned(db, Deployment, body.deployment_id, actor)
    version = db.get(AgentVersion, deployment.version_id)
    if not deployment.active or not version.approved_at or version.org_id != actor.org_id:
        raise HTTPException(409, "Only an active deployment of an approved version can be installed")
    spec = version.spec
    properties = spec.get("input_schema", {}).get("properties", {})
    if (
        spec.get("tools")
        or spec.get("connection_ids")
        or spec.get("generated_tools")
        or list(properties) != [operation.document_field]
    ):
        raise HTTPException(422, "The new version does not take the same single document as its request")
    if operation_kind(spec) != operation.kind:
        raise HTTPException(422, "The new version reads a different kind of document")
    current = db.get(Deployment, operation.deployment_id)
    number = db.scalar(select(func.max(AgentVersion.number)).where(AgentVersion.agent_id == current.agent_id)) or 0
    installed = AgentVersion(
        org_id=org.id,
        agent_id=current.agent_id,
        number=number + 1,
        spec=spec,
        hypothesis=f"Upgraded to version {version.number} of the builder's agent"[:1000],
        approved_at=now(),
        approved_by=actor.user_id,
    )
    db.add(installed)
    db.flush()
    placed = Deployment(org_id=org.id, agent_id=current.agent_id, version_id=installed.id, policy=dict(current.policy))
    db.add(placed)
    db.flush()
    current.active = False
    db.get(AgentRecord, current.agent_id).best_version_id = installed.id
    operation.deployment_id = placed.id
    operation.source = {
        "org_id": actor.org_id,
        "agent_id": deployment.agent_id,
        "version_id": version.id,
        "version": version.number,
    }
    audit(
        db, Principal(actor.user_id, org.id, "admin"), "operation_upgraded", operation.id, {"version_id": installed.id}
    )
    audit(db, actor, "operation_upgraded_for_customer", operation.id, {"customer": org.id, "version_id": version.id})
    db.commit()
    again = 0
    if body.reprocess:
        waiting = db.scalars(
            select(InboxDocument)
            .where(InboxDocument.operation_id == operation.id, InboxDocument.stage.not_in(("approved", "exported")))
            .order_by(InboxDocument.created_at)
        )
        for document in list(waiting):
            if document.pages:
                await reprocess(db, operation, document)
                again += 1
    return {**customer_view(db, org), "reprocessed": again}


class OperationUpdate(StrictModel):
    enabled: bool


@router.patch("/customers/{org_id}/operations/{operation_id}")
def update_operation(org_id: str, operation_id: str, body: OperationUpdate, actor=ACTOR, db=DB):
    org = customer_org(db, actor, org_id)
    operation = db.get(Operation, operation_id)
    if not operation or operation.org_id != org.id:
        raise HTTPException(404, "Resource not found")
    operation.enabled = body.enabled
    audit(db, Principal(actor.user_id, org.id, "admin"), "operation_updated", operation.id, {"enabled": body.enabled})
    db.commit()
    return customer_view(db, org)


class InviteCustomer(StrictModel):
    email: str = Field(min_length=3, max_length=320)


@router.post("/customers/{org_id}/invitations", status_code=201)
def invite_customer(org_id: str, body: InviteCustomer, actor=ACTOR, db=DB):
    """Invite one of the customer's people into their workspace, with the customer role."""
    from factory.memberships import CreateInvitation, create_invitation

    org = customer_org(db, actor, org_id)
    request = CreateInvitation(email=body.email, role="customer")
    return create_invitation(request, actor=Principal(actor.user_id, org.id, "admin"), db=db)
