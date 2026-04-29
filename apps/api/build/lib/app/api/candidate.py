from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import SessionCreate, SessionEventCreate, SubmissionCreate, TrackVersionRead
from app.services.platform import (
    append_session_event,
    create_session,
    create_submission,
    get_report_or_404,
    get_session_or_404,
    list_active_tracks,
    serialize_report,
    serialize_session,
)

router = APIRouter(prefix="/candidate", tags=["candidate"])


@router.get("/tracks", response_model=list[TrackVersionRead])
def list_tracks(db: Session = Depends(get_db)):
    return list_active_tracks(db)


@router.post("/sessions")
def launch_session(payload: SessionCreate, db: Session = Depends(get_db)):
    session = create_session(db, payload)
    return {"session": serialize_session(session)}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    return {"session": serialize_session(get_session_or_404(db, session_id))}


@router.post("/sessions/{session_id}/events")
def log_session_event(session_id: str, payload: SessionEventCreate, db: Session = Depends(get_db)):
    session = append_session_event(db, session_id, payload)
    return {"session": serialize_session(session)}


@router.post("/submissions")
def submit_work_sample(payload: SubmissionCreate, db: Session = Depends(get_db)):
    return create_submission(db, payload)


@router.get("/reports/{report_id}")
def get_candidate_report(report_id: str, db: Session = Depends(get_db)):
    report = get_report_or_404(db, report_id)
    return {"report": serialize_report(report)}

