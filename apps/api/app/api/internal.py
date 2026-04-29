from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import AuthContext, require_admin_auth, require_admin_csrf, require_reviewer_auth, require_reviewer_csrf
from app.db.session import get_db
from app.schemas import (
    AttemptCreate,
    CalibrationRunCreate,
    ReportAccessRevokeCreate,
    ReviewerAssignmentCreate,
    ReviewerClaimCreate,
    ReviewPublishCreate,
)
from app.services.platform import (
    claim_reviewer_assignment,
    create_attempt,
    create_calibration_run,
    create_reviewer_assignment,
    get_internal_report_detail,
    get_runtime_status,
    list_attempts,
    list_runtime_previews,
    list_review_queue,
    list_runtime_workspaces,
    publish_employer_review,
    queue_runtime_cleanup,
    release_reviewer_assignment,
    revoke_report_access,
    serialize_attempt,
)
from app.services.runtime_maintenance import runtime_maintenance

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/review-queue")
def get_review_queue(db: Session = Depends(get_db), _: AuthContext = Depends(require_reviewer_auth)):
    return {"items": list_review_queue(db)}


@router.get("/reports/{report_id}")
def get_internal_report(report_id: str, db: Session = Depends(get_db), _: AuthContext = Depends(require_reviewer_auth)):
    return get_internal_report_detail(db, report_id)


@router.get("/attempts")
def get_attempts(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: AuthContext = Depends(require_reviewer_auth),
):
    return {"items": [serialize_attempt(item) for item in list_attempts(db, status=status, limit=limit)]}


@router.post("/attempts")
def create_attempt_record(
    payload: AttemptCreate,
    db: Session = Depends(get_db),
    _: AuthContext = Depends(require_admin_auth),
):
    attempt = create_attempt(db, payload)
    return {"attempt": serialize_attempt(attempt)}


@router.post("/reviewer/assignments")
def assign_reviewer(
    payload: ReviewerAssignmentCreate,
    db: Session = Depends(get_db),
    _: AuthContext = Depends(require_admin_auth),
):
    assignment = create_reviewer_assignment(db, payload)
    return {
        "assignment": {
            "id": assignment.id,
            "submission_id": assignment.submission_id,
            "reviewer_id": assignment.reviewer_id,
            "status": assignment.status,
        }
    }


@router.post("/reviewer/assignments/claim")
def claim_reviewer(
    payload: ReviewerClaimCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_reviewer_csrf),
):
    assignment = claim_reviewer_assignment(db, payload, reviewer_id=context.user.id)
    return {
        "assignment": {
            "id": assignment.id,
            "submission_id": assignment.submission_id,
            "reviewer_id": assignment.reviewer_id,
            "status": assignment.status,
            "claimed_at": assignment.claimed_at.isoformat() if assignment.claimed_at else None,
        }
    }


@router.post("/reviewer/assignments/{submission_id}/release")
def release_reviewer(
    submission_id: str,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_reviewer_csrf),
):
    assignment = release_reviewer_assignment(db, submission_id, context.user.id)
    return {
        "assignment": {
            "id": assignment.id,
            "submission_id": assignment.submission_id,
            "reviewer_id": assignment.reviewer_id,
            "status": assignment.status,
            "released_at": assignment.released_at.isoformat() if assignment.released_at else None,
        }
    }


@router.post("/calibration/runs")
def create_calibration(
    payload: CalibrationRunCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_reviewer_auth),
):
    calibration = create_calibration_run(db, payload.model_copy(update={"initiated_by": context.user.id}))
    return {
        "calibration": {
            "id": calibration.id,
            "track_version_id": calibration.track_version_id,
            "sample_size": calibration.sample_size,
            "result_summary": calibration.result_summary_json,
        }
    }


@router.post("/reviews/publish")
def publish_review(
    payload: ReviewPublishCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_reviewer_csrf),
):
    return publish_employer_review(db, payload, actor_id=context.user.id)


@router.post("/report-access/{token}/revoke")
def revoke_access(
    token: str,
    payload: ReportAccessRevokeCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_reviewer_csrf),
):
    access = revoke_report_access(db, token, actor_id=context.user.id, reason=payload.reason)
    return {
        "access": {
            "id": access.id,
            "token": access.token,
            "status": access.status,
            "revoked_at": access.revoked_at.isoformat() if access.revoked_at else None,
        }
    }


@router.post("/runtime/cleanup")
def cleanup_runtime(db: Session = Depends(get_db), _: AuthContext = Depends(require_admin_csrf)):
    return queue_runtime_cleanup(db, trigger="manual")


@router.get("/runtime/status")
def get_runtime_health(_: AuthContext = Depends(require_admin_auth)):
    return {
        "runtime": get_runtime_status(),
        "maintenance": runtime_maintenance.status(),
    }


@router.get("/runtime/workspaces")
def get_runtime_workspaces(limit: int = Query(default=10, ge=1, le=100), _: AuthContext = Depends(require_admin_auth)):
    return {"items": list_runtime_workspaces(limit=limit)}


@router.get("/runtime/previews")
def get_runtime_previews(limit: int = Query(default=10, ge=1, le=100), _: AuthContext = Depends(require_admin_auth)):
    return {"items": list_runtime_previews(limit=limit)}
