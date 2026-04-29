from __future__ import annotations

from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from app.api.dependencies import AuthContext, require_candidate_auth
from app.db.models import Report, ReportAccess, ReportAccessStatus, ReportAccessType, Submission, TrackVersion
from app.db.session import get_db
from app.runtime.preview import PreviewUnavailableError, preview_manager
from app.services.platform import get_session_or_404, preview_config_for_track, preview_enabled_for_track

router = APIRouter(prefix="/preview", tags=["preview"])

PREVIEW_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


def _rewrite_location(location: str, proxy_base_path: str, local_url: str | None) -> str:
    if local_url and location.startswith(local_url):
        suffix = location.removeprefix(local_url)
        return f"{proxy_base_path}{suffix if suffix.startswith('/') else f'/{suffix}'}"
    if location.startswith("/"):
        return f"{proxy_base_path}{location}"
    return location


def _rewrite_html_content(content: bytes, proxy_base_path: str) -> bytes:
    try:
        html = content.decode("utf-8")
    except UnicodeDecodeError:
        return content

    replacements = {
        "url: '/openapi.json'": f"url: '{proxy_base_path}/openapi.json'",
        'url: "/openapi.json"': f'url: "{proxy_base_path}/openapi.json"',
        "oauth2RedirectUrl: window.location.origin + '/docs/oauth2-redirect'": (
            f"oauth2RedirectUrl: window.location.origin + '{proxy_base_path}/docs/oauth2-redirect'"
        ),
        'oauth2RedirectUrl: window.location.origin + "/docs/oauth2-redirect"': (
            f'oauth2RedirectUrl: window.location.origin + "{proxy_base_path}/docs/oauth2-redirect"'
        ),
    }
    for source, target in replacements.items():
        html = html.replace(source, target)

    html = re.sub(r'((?:href|src)=["\'])/(?!/)', rf"\1{proxy_base_path}/", html)
    return html.encode("utf-8")


def _build_response(proxy_result: dict, proxy_base_path: str, local_url: str | None) -> Response:
    content = proxy_result["content"]
    content_type = ""
    for key, value in proxy_result["headers"].items():
        if key.lower() == "content-type":
            content_type = value
            break
    if "text/html" in content_type.lower():
        content = _rewrite_html_content(content, proxy_base_path)

    response = Response(content=content, status_code=proxy_result["status_code"])
    for key, value in proxy_result["headers"].items():
        lower = key.lower()
        if lower in {"content-length", "transfer-encoding", "connection"}:
            continue
        if lower == "location":
            response.headers[key] = _rewrite_location(value, proxy_base_path, local_url)
            continue
        response.headers[key] = value
    return response


async def _request_body_or_empty(request: Request) -> bytes:
    try:
        return await request.body()
    except ClientDisconnect:
        return b""


async def _proxy_live(session_id: str, path: str, request: Request, db: Session, user_id: str) -> Response:
    session = get_session_or_404(db, session_id)
    if session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Preview not found")
    track = db.query(TrackVersion).filter(TrackVersion.id == session.track_version_id).first()
    if not track or not preview_enabled_for_track(track):
        raise HTTPException(status_code=409, detail="Preview is not configured for this track")

    handle = preview_manager.live_handle(session_id=session.id, workspace_id=session.workspace_id)
    summary = preview_manager.get(handle)
    if summary.get("status") != "ready":
        raise HTTPException(status_code=409, detail="Preview is not ready")

    try:
        proxy_result = preview_manager.proxy_request(
            handle,
            summary,
            method=request.method,
            request_path=f"/{path}" if path else "/",
            query_string=request.url.query,
            headers=dict(request.headers),
            body=await _request_body_or_empty(request),
        )
    except PreviewUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _build_response(proxy_result, f"/api/preview/live/{session.id}", summary.get("local_url"))


def _ensure_frozen_preview(db: Session, preview_share_token: str) -> tuple[Submission, dict]:
    access = db.query(ReportAccess).filter(
        ReportAccess.token == preview_share_token,
        ReportAccess.access_type == ReportAccessType.preview.value,
    ).first()
    if not access:
        raise HTTPException(status_code=404, detail="Preview not found")
    if access.status != ReportAccessStatus.active.value:
        raise HTTPException(status_code=409, detail="Preview access is not active")
    if access.expires_at and access.expires_at < datetime.utcnow():
        access.status = ReportAccessStatus.expired.value
        db.add(access)
        db.commit()
        raise HTTPException(status_code=409, detail="Preview access has expired")

    report = db.query(Report).filter(Report.id == access.report_id).first()
    if not report or not report.is_portable:
        raise HTTPException(status_code=409, detail="Frozen preview is unavailable until the report is portable")
    submission = db.query(Submission).filter(Submission.id == (access.submission_id or report.submission_id)).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Preview submission not found")
    track = db.query(TrackVersion).filter(TrackVersion.id == submission.track_version_id).first()
    if not track or not preview_enabled_for_track(track):
        raise HTTPException(status_code=409, detail="Preview is not configured for this track")
    access.last_accessed_at = datetime.utcnow()
    db.add(access)
    db.commit()

    handle = preview_manager.frozen_handle(submission_id=submission.id)
    summary = preview_manager.get(handle)
    if summary.get("status") != "ready":
        try:
            summary = preview_manager.start(handle, preview_config_for_track(track), image_ref=track.container_image_ref)
        except PreviewUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return submission, summary


async def _proxy_frozen(preview_share_token: str, path: str, request: Request, db: Session) -> Response:
    submission, summary = _ensure_frozen_preview(db, preview_share_token)
    handle = preview_manager.frozen_handle(submission_id=submission.id)
    try:
        proxy_result = preview_manager.proxy_request(
            handle,
            summary,
            method=request.method,
            request_path=f"/{path}" if path else "/",
            query_string=request.url.query,
            headers=dict(request.headers),
            body=await _request_body_or_empty(request),
        )
    except PreviewUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _build_response(proxy_result, f"/api/preview/frozen/{preview_share_token}", summary.get("local_url"))


@router.api_route("/live/{session_id}", methods=PREVIEW_METHODS)
async def proxy_live_root(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_auth),
):
    return await _proxy_live(session_id, "", request, db, context.user.id)


@router.api_route("/live/{session_id}/{path:path}", methods=PREVIEW_METHODS)
async def proxy_live_path(
    session_id: str,
    path: str,
    request: Request,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_auth),
):
    return await _proxy_live(session_id, path, request, db, context.user.id)


@router.api_route("/frozen/{preview_share_token}", methods=PREVIEW_METHODS)
async def proxy_frozen_root(preview_share_token: str, request: Request, db: Session = Depends(get_db)):
    return await _proxy_frozen(preview_share_token, "", request, db)


@router.api_route("/frozen/{preview_share_token}/{path:path}", methods=PREVIEW_METHODS)
async def proxy_frozen_path(preview_share_token: str, path: str, request: Request, db: Session = Depends(get_db)):
    return await _proxy_frozen(preview_share_token, path, request, db)
