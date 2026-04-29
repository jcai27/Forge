from fastapi import APIRouter

from app.api.candidate import router as candidate_router
from app.api.employer import router as employer_router
from app.api.internal import router as internal_router

router = APIRouter()
router.include_router(candidate_router)
router.include_router(employer_router)
router.include_router(internal_router)

