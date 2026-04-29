from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import (
    AssignmentStatus,
    EventType,
    ReviewDecision,
    ReviewDraftState,
    SubmissionVisibility,
)


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
    preview_config_json: dict[str, Any]
    content_metadata_json: dict[str, Any]


class SessionCreate(BaseModel):
    attempt_id: str | None = None
    track_version_id: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "SessionCreate":
        if self.attempt_id:
            return self
        if self.track_version_id:
            return self
        raise ValueError("Either attempt_id or track_version_id must be provided")


class SessionEventCreate(BaseModel):
    event_type: EventType
    occurred_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkspaceFileWrite(BaseModel):
    path: str = Field(min_length=1)
    content: str = ""
    expected_updated_at: str | None = None


class WorkspaceFileRename(BaseModel):
    old_path: str = Field(min_length=1)
    new_path: str = Field(min_length=1)


class WorkspaceCommandCreate(BaseModel):
    command: str = Field(min_length=1)


class WorkspaceAssistantRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    selected_path: str | None = None
    open_paths: list[str] = Field(default_factory=list)


class PreviewRead(BaseModel):
    scope: str
    subject_id: str
    status: str
    backend: str | None = None
    proxy_base_path: str | None = None
    default_url: str | None = None
    readiness_path: str | None = None
    local_url: str | None = None
    port: int | None = None
    started_at: str | None = None
    last_ready_at: str | None = None
    last_accessed_at: str | None = None
    stopped_at: str | None = None
    error: str | None = None
    log_path: str | None = None


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
    candidate_summary_note: str = ""
    tradeoff_note: str = ""
    unfinished_work_note: str = ""
    submission_checklist: dict[str, bool] = Field(default_factory=dict)


class RubricDimensionScore(BaseModel):
    dimension: str
    score: float
    notes: str = ""


class EmployerReviewCreate(BaseModel):
    submission_id: str
    decision: ReviewDecision
    confidence: float = Field(ge=0, le=1)
    rubric_scores: list[RubricDimensionScore] = Field(default_factory=list)
    notes: str = ""
    reviewer_annotations: dict[str, Any] = Field(default_factory=dict)
    escalation_state: str | None = None
    state: ReviewDraftState = ReviewDraftState.draft


class ReviewPublishCreate(BaseModel):
    review_id: str
    visibility: SubmissionVisibility = SubmissionVisibility.unlisted


class ReportAccessRevokeCreate(BaseModel):
    reason: str = ""


class ReviewerAssignmentCreate(BaseModel):
    submission_id: str
    reviewer_id: str
    status: AssignmentStatus = AssignmentStatus.queued
    due_at: datetime | None = None


class ReviewerClaimCreate(BaseModel):
    submission_id: str
    due_at: datetime | None = None


class AttemptCreate(BaseModel):
    user_id: str
    track_version_id: str
    organization_id: str | None = None
    candidate_label: str | None = None
    notes: str = ""
    expires_at: datetime | None = None


class SessionHeartbeatCreate(BaseModel):
    at: datetime | None = None


class CalibrationRunCreate(BaseModel):
    track_version_id: str
    initiated_by: str
    notes: str = ""
    sample_size: int = Field(default=5, ge=1)


class LoginRequest(BaseModel):
    email: str
    password: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class CandidateMagicLinkRequest(BaseModel):
    invite_token: str
    email: str


class CandidateMagicLinkRedeem(BaseModel):
    token: str


class MfaVerifyRequest(BaseModel):
    code: str = Field(min_length=6)
