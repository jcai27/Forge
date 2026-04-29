import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func

from app.db.session import Base


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UserType(str, enum.Enum):
    candidate = "candidate"
    employer = "employer"
    admin = "admin"


class SessionStatus(str, enum.Enum):
    launched = "launched"
    active = "active"
    submitted = "submitted"
    expired = "expired"


class EventType(str, enum.Enum):
    ide_edit = "ide_edit"
    terminal_command = "terminal_command"
    test_run = "test_run"
    checkpoint = "checkpoint"
    ai_request = "ai_request"
    ai_response = "ai_response"
    paste = "paste"


class SubmissionVisibility(str, enum.Enum):
    private = "private"
    unlisted = "unlisted"
    public = "public"


class ReviewState(str, enum.Enum):
    pending_review = "pending_review"
    human_reviewed = "human_reviewed"
    flagged = "flagged"


class ReportStatus(str, enum.Enum):
    pending_review = "pending_review"
    ready = "ready"
    flagged = "flagged"


class ReviewDecision(str, enum.Enum):
    pending = "pending"
    advance = "advance"
    interview = "interview"
    reject = "reject"
    offer = "offer"


class AssignmentStatus(str, enum.Enum):
    queued = "queued"
    in_review = "in_review"
    completed = "completed"


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    billing_plan = Column(String, nullable=False, default="design_partner")
    settings_json = Column(JSON, nullable=False, default=dict)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    full_name = Column(String, nullable=False)
    user_type = Column(String, nullable=False)
    auth_provider = Column(String, nullable=False, default="seeded")
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=True)
    profile_json = Column(JSON, nullable=False, default=dict)


class TrackVersion(TimestampMixin, Base):
    __tablename__ = "track_versions"

    id = Column(String, primary_key=True)
    slug = Column(String, nullable=False, unique=True)
    title = Column(String, nullable=False)
    role_family = Column(String, nullable=False)
    version = Column(String, nullable=False)
    prompt_markdown = Column(Text, nullable=False)
    starter_repo_ref = Column(String, nullable=False)
    container_image_ref = Column(String, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    allowed_tools_json = Column(JSON, nullable=False, default=dict)
    rubric_template_json = Column(JSON, nullable=False, default=dict)
    benchmark_config_json = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)


class Session(TimestampMixin, Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    track_version_id = Column(String, ForeignKey("track_versions.id"), nullable=False)
    workspace_id = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default=SessionStatus.launched.value)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    telemetry_summary_json = Column(JSON, nullable=False, default=dict)
    integrity_summary_json = Column(JSON, nullable=False, default=dict)


class SessionEvent(TimestampMixin, Base):
    __tablename__ = "session_events"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    event_type = Column(String, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    payload_json = Column(JSON, nullable=False, default=dict)


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("session_id", name="uq_submission_session"),)

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    track_version_id = Column(String, ForeignKey("track_versions.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    artifact_uri = Column(String, nullable=True)
    artifact_sha = Column(String, nullable=True)
    build_log_uri = Column(String, nullable=True)
    test_log_uri = Column(String, nullable=True)
    immutable_snapshot_json = Column(JSON, nullable=False, default=dict)
    automated_score_json = Column(JSON, nullable=False, default=dict)
    provenance_summary_json = Column(JSON, nullable=False, default=dict)
    benchmark_summary_json = Column(JSON, nullable=False, default=dict)
    visibility = Column(String, nullable=False, default=SubmissionVisibility.private.value)
    review_state = Column(String, nullable=False, default=ReviewState.pending_review.value)
    share_token = Column(String, nullable=False, unique=True)


class Report(TimestampMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("submission_id", name="uq_report_submission"),)

    id = Column(String, primary_key=True)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False)
    visibility = Column(String, nullable=False, default=SubmissionVisibility.private.value)
    status = Column(String, nullable=False, default=ReportStatus.pending_review.value)
    candidate_summary_json = Column(JSON, nullable=False, default=dict)
    employer_summary_json = Column(JSON, nullable=False, default=dict)
    is_portable = Column(Boolean, nullable=False, default=False)
    published_at = Column(DateTime(timezone=True), nullable=True)


class EmployerReview(TimestampMixin, Base):
    __tablename__ = "employer_reviews"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False)
    reviewer_id = Column(String, ForeignKey("users.id"), nullable=False)
    decision = Column(String, nullable=False, default=ReviewDecision.pending.value)
    confidence = Column(Float, nullable=False, default=0.5)
    rubric_scores_json = Column(JSON, nullable=False, default=list)
    notes = Column(Text, nullable=False, default="")
    completed_at = Column(DateTime(timezone=True), nullable=True)


class ReviewerAssignment(TimestampMixin, Base):
    __tablename__ = "reviewer_assignments"

    id = Column(String, primary_key=True)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False)
    reviewer_id = Column(String, ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False, default=AssignmentStatus.queued.value)
    due_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class CalibrationRun(TimestampMixin, Base):
    __tablename__ = "calibration_runs"

    id = Column(String, primary_key=True)
    track_version_id = Column(String, ForeignKey("track_versions.id"), nullable=False)
    initiated_by = Column(String, ForeignKey("users.id"), nullable=False)
    notes = Column(Text, nullable=False, default="")
    sample_size = Column(Integer, nullable=False, default=0)
    result_summary_json = Column(JSON, nullable=False, default=dict)
    completed_at = Column(DateTime(timezone=True), nullable=True)

