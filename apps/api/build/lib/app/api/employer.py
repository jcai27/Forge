from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import EmployerReviewCreate
from app.services.platform import create_employer_review, get_employer_report_by_token

router = APIRouter(prefix="/employer", tags=["employer"])


@router.get("/reports/{share_token}")
def get_employer_report(share_token: str, db: Session = Depends(get_db)):
    return get_employer_report_by_token(db, share_token)


@router.post("/reviews")
def submit_employer_review(payload: EmployerReviewCreate, db: Session = Depends(get_db)):
    return create_employer_review(db, payload)

