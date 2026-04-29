from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import CalibrationRunCreate, ReviewerAssignmentCreate
from app.services.platform import create_calibration_run, create_reviewer_assignment, list_review_queue

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/review-queue")
def get_review_queue(db: Session = Depends(get_db)):
    return {"items": list_review_queue(db)}


@router.post("/reviewer/assignments")
def assign_reviewer(payload: ReviewerAssignmentCreate, db: Session = Depends(get_db)):
    assignment = create_reviewer_assignment(db, payload)
    return {
        "assignment": {
            "id": assignment.id,
            "submission_id": assignment.submission_id,
            "reviewer_id": assignment.reviewer_id,
            "status": assignment.status,
        }
    }


@router.post("/calibration/runs")
def create_calibration(payload: CalibrationRunCreate, db: Session = Depends(get_db)):
    calibration = create_calibration_run(db, payload)
    return {
        "calibration": {
            "id": calibration.id,
            "track_version_id": calibration.track_version_id,
            "sample_size": calibration.sample_size,
            "result_summary": calibration.result_summary_json,
        }
    }

