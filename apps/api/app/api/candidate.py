import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.api.dependencies import AuthContext, build_dev_auth_context, require_candidate_auth, require_candidate_csrf, resolve_dev_auth_role
from app.core.config import settings
from app.db.models import AssessmentAttempt, Submission
from app.db.session import SessionLocal, get_db
from app.schemas import (
    SessionCreate,
    WorkspaceAssistantRequest,
    SessionEventCreate,
    SessionHeartbeatCreate,
    SubmissionCreate,
    TrackVersionRead,
    WorkspaceCommandCreate,
    WorkspaceFileWrite,
    WorkspaceFileRename,
)
from app.services.ai_editor import apply_workspace_assistant
from app.services.platform import (
    append_session_event,
    create_session,
    get_attempt_or_404,
    create_submission,
    get_live_preview_status,
    get_report_or_404,
    get_runtime_job,
    get_session_or_404,
    heartbeat_session,
    list_active_tracks,
    list_workspace_tree,
    provision_session_workspace,
    read_workspace_file,
    retry_session_provision,
    run_workspace_command,
    run_workspace_tests,
    serialize_report,
    serialize_session,
    start_live_preview,
    stop_live_preview,
    write_workspace_file,
    delete_workspace_file,
    rename_workspace_file,
    search_workspace,
    list_workspace_checkpoints,
    restore_checkpoint,
)
from app.services.auth import get_login_session_from_cookie

router = APIRouter(prefix="/candidate", tags=["candidate"])


def _ensure_attempt_owner(db: Session, attempt_id: str, user_id: str) -> AssessmentAttempt:
    attempt = get_attempt_or_404(db, attempt_id)
    if attempt.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment attempt not found")
    return attempt


def _ensure_session_owner(db: Session, session_id: str, user_id: str):
    session = get_session_or_404(db, session_id)
    if session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


@router.get("/tracks", response_model=list[TrackVersionRead])
def list_tracks(db: Session = Depends(get_db), _: AuthContext = Depends(require_candidate_auth)):
    return list_active_tracks(db)


@router.post("/sessions")
def launch_session(
    payload: SessionCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    if payload.attempt_id:
        _ensure_attempt_owner(db, payload.attempt_id, context.user.id)
    session = create_session(db, payload, user_id=context.user.id)
    if session.status == "queued":
        session, job = provision_session_workspace(db, session.id)
        return {"session": serialize_session(session, job)}
    return {"session": serialize_session(session, get_runtime_job(db, session.id))}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db), context: AuthContext = Depends(require_candidate_auth)):
    session = _ensure_session_owner(db, session_id, context.user.id)
    return {"session": serialize_session(session, get_runtime_job(db, session.id))}


@router.post("/sessions/{session_id}/heartbeat")
def beat_session(
    session_id: str,
    payload: SessionHeartbeatCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    session = heartbeat_session(db, session_id, payload.at)
    return {"session": serialize_session(session, get_runtime_job(db, session.id))}


@router.post("/sessions/{session_id}/retry")
def retry_session(
    session_id: str,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    session, job = retry_session_provision(db, session_id)
    return {"session": serialize_session(session, job)}


@router.get("/sessions/{session_id}/workspace/tree")
def get_workspace_tree(session_id: str, db: Session = Depends(get_db), context: AuthContext = Depends(require_candidate_auth)):
    _ensure_session_owner(db, session_id, context.user.id)
    return list_workspace_tree(db, session_id)


@router.get("/sessions/{session_id}/workspace/file")
def get_workspace_file(
    session_id: str,
    path: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_auth),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return read_workspace_file(db, session_id, path)


@router.put("/sessions/{session_id}/workspace/file")
def save_workspace_file(
    session_id: str,
    payload: WorkspaceFileWrite,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return write_workspace_file(
        db,
        session_id,
        path=payload.path,
        content=payload.content,
        expected_updated_at=payload.expected_updated_at,
    )


@router.delete("/sessions/{session_id}/workspace/file")
def delete_file(
    session_id: str,
    path: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return delete_workspace_file(db, session_id, path)


@router.post("/sessions/{session_id}/workspace/file/rename")
def rename_file(
    session_id: str,
    payload: WorkspaceFileRename,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return rename_workspace_file(db, session_id, payload.old_path, payload.new_path)


@router.get("/sessions/{session_id}/workspace/search")
def search_files(
    session_id: str,
    query: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_auth),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return search_workspace(db, session_id, query)


@router.get("/sessions/{session_id}/checkpoints")
def list_checkpoints_route(session_id: str, db: Session = Depends(get_db), context: AuthContext = Depends(require_candidate_auth)):
    _ensure_session_owner(db, session_id, context.user.id)
    return list_workspace_checkpoints(db, session_id)


@router.post("/sessions/{session_id}/checkpoints/{checkpoint_id}/restore")
def restore_cp(
    session_id: str,
    checkpoint_id: str,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return restore_checkpoint(db, session_id, checkpoint_id)


@router.post("/sessions/{session_id}/events")
def log_session_event(
    session_id: str,
    payload: SessionEventCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    session = append_session_event(db, session_id, payload)
    return {"session": serialize_session(session)}


@router.post("/sessions/{session_id}/commands/run")
def run_command(
    session_id: str,
    payload: WorkspaceCommandCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return run_workspace_command(db, session_id, payload.command)


@router.post("/sessions/{session_id}/commands/test")
def run_tests(
    session_id: str,
    payload: WorkspaceCommandCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return run_workspace_tests(db, session_id, payload.command)


@router.post("/sessions/{session_id}/assistant")
def run_workspace_assistant(
    session_id: str,
    payload: WorkspaceAssistantRequest,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return apply_workspace_assistant(db, session_id=session_id, payload=payload)


@router.post("/sessions/{session_id}/preview/start")
def start_preview(
    session_id: str,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return start_live_preview(db, session_id)


@router.get("/sessions/{session_id}/preview")
def get_preview(session_id: str, db: Session = Depends(get_db), context: AuthContext = Depends(require_candidate_auth)):
    _ensure_session_owner(db, session_id, context.user.id)
    return get_live_preview_status(db, session_id)


@router.post("/sessions/{session_id}/preview/stop")
def stop_preview(
    session_id: str,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, session_id, context.user.id)
    return stop_live_preview(db, session_id)


@router.post("/submissions")
def submit_work_sample(
    payload: SubmissionCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_candidate_csrf),
):
    _ensure_session_owner(db, payload.session_id, context.user.id)
    return create_submission(db, payload)


@router.get("/reports/{report_id}")
def get_candidate_report(report_id: str, db: Session = Depends(get_db), context: AuthContext = Depends(require_candidate_auth)):
    report = get_report_or_404(db, report_id)
    submission = db.query(Submission).filter(Submission.id == report.submission_id).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    owner_session = get_session_or_404(db, submission.session_id)
    if owner_session.user_id != context.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return {"report": serialize_report(report)}


@router.websocket("/sessions/{session_id}/pty")
async def websocket_pty(websocket: WebSocket, session_id: str):
    session_cookie = websocket.cookies.get(settings.auth_session_cookie_name)
    db = SessionLocal()
    login_session = get_login_session_from_cookie(db, session_cookie)
    context = build_dev_auth_context(db, resolve_dev_auth_role(websocket)) if not login_session else None
    acting_user_id = login_session.user_id if login_session else context.user.id if context else None
    session = get_session_or_404(db, session_id) if acting_user_id else None
    if not acting_user_id or not session or session.user_id != acting_user_id:
        await websocket.close(code=4401, reason="Authentication required")
        db.close()
        return
    await websocket.accept()

    from app.services.platform import runtime_provisioner
    summary = runtime_provisioner.workspace_summary(session.workspace_id)
    if not summary or "container_name" not in summary:
        await websocket.close(code=1011, reason="Container not running")
        db.close()
        return

    container_name = summary["container_name"]

    process = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", container_name, "sh",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async def read_from_pty():
        try:
            while True:
                data = await process.stdout.read(1024)
                if not data:
                    break
                await websocket.send_text(data.decode(errors="replace"))
        except Exception:
            pass

    async def write_to_pty():
        try:
            while True:
                data = await websocket.receive_text()
                if process.stdin:
                    process.stdin.write(data.encode())
                    await process.stdin.drain()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    task1 = asyncio.create_task(read_from_pty())
    task2 = asyncio.create_task(write_to_pty())
    
    _, pending = await asyncio.wait([task1, task2], return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()

    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    db.close()
