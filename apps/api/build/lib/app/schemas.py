from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AssignmentStatus, EventType, ReviewDecision, SubmissionVisibility


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TrackVersionRead(ORMModel):
    id: str
    slug: str
    title: str
    role_family: str
    version: str
    duration_minutes: int
    starter_repo_ref: str
    container_image_ref: str
    allowed_tools_json: dict[str, Any]
    rubric_template_json: dict[str, Any]


class SessionCreate(BaseModel):
    user_id: str
    track_version_id: str


class SessionEventCreate(BaseModel):
    event_type: EventType
    occurred_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AutomatedResultOverride(BaseModel):
    passed_tests: int | None = None
    total_tests: int | None = None
    build_success: bool | None = None
    lint_passed: bool | None = None
    typecheck_passed: bool | None = None
    security_passed: bool | None = None


class SubmissionCreate(BaseModel):
    session_id: str
    visibility: SubmissionVisibility = SubmissionVisibility.private
    artifact_uri: str | None = None
    artifact_sha: str | None = None
    build_log_uri: str | None = None
    test_log_uri: str | None = None
    immutable_snapshot: dict[str, Any] = Field(default_factory=dict)
    automated_result_override: AutomatedResultOverride | None = None


class RubricDimensionScore(BaseModel):
    dimension: str
    score: float
    notes: str = ""


class EmployerReviewCreate(BaseModel):
    organization_id: str
    submission_id: str
    reviewer_id: str
    decision: ReviewDecision
    confidence: float = Field(ge=0, le=1)
    rubric_scores: list[RubricDimensionScore]
    notes: str = ""


class ReviewerAssignmentCreate(BaseModel):
    submission_id: str
    reviewer_id: str
    status: AssignmentStatus = AssignmentStatus.queued
    due_at: datetime | None = None


class CalibrationRunCreate(BaseModel):
    track_version_id: str
    initiated_by: str
    notes: str = ""
    sample_size: int = Field(default=5, ge=1)

