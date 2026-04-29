from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import AuthContext, require_reviewer_csrf
from app.db.session import get_db
from app.schemas import EmployerReviewCreate
from app.services.platform import create_employer_review, get_employer_report_by_token, get_frozen_preview_by_token

router = APIRouter(prefix="/employer", tags=["employer"])


@router.get("/reports/{share_token}")
def get_employer_report(share_token: str, db: Session = Depends(get_db)):
    return get_employer_report_by_token(db, share_token)


@router.post("/reviews")
def submit_employer_review(
    payload: EmployerReviewCreate,
    db: Session = Depends(get_db),
    context: AuthContext = Depends(require_reviewer_csrf),
):
    if not context.user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return create_employer_review(
        db,
        payload,
        reviewer_id=context.user.id,
        organization_id=context.user.organization_id or "",
    )


@router.get("/previews/{preview_share_token}")
def get_employer_preview(preview_share_token: str, db: Session = Depends(get_db)):
    return get_frozen_preview_by_token(db, preview_share_token)
