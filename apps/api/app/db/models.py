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
    queued = "queued"
    provisioning = "provisioning"
    ready = "ready"
    runtime_failed = "runtime_failed"
    submitting = "submitting"
    launched = "launched"
    active = "active"
    submitted = "submitted"
    expired = "expired"
    cleanup_pending = "cleanup_pending"
    cleaned = "cleaned"


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
    in_review = "in_review"
    second_review_required = "second_review_required"
    human_reviewed = "human_reviewed"
    flagged = "flagged"
    published = "published"


class ReportStatus(str, enum.Enum):
    draft = "draft"
    pending_review = "pending_review"
    ready = "ready"
    flagged = "flagged"
    revoked = "revoked"


class ReviewDecision(str, enum.Enum):
    pending = "pending"
    advance = "advance"
    interview = "interview"
    reject = "reject"
    offer = "offer"


class AssignmentStatus(str, enum.Enum):
    queued = "queued"
    claimed = "claimed"
    released = "released"
    in_review = "in_review"
    completed = "completed"


class AttemptStatus(str, enum.Enum):
    pending = "pending"
    session_launched = "session_launched"
    completed = "completed"
    expired = "expired"
    cancelled = "cancelled"


class RuntimeJobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    poisoned = "poisoned"


class ReviewDraftState(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    published = "published"


class EscalationState(str, enum.Enum):
    none = "none"
    flagged = "flagged"
    second_review_required = "second_review_required"
    resolved = "resolved"


class ReportAccessType(str, enum.Enum):
    report = "report"
    preview = "preview"


class ReportAccessStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"
    expired = "expired"


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


class Credential(TimestampMixin, Base):
    __tablename__ = "credentials"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    password_version = Column(Integer, nullable=False, default=1)
    must_change_password = Column(Boolean, nullable=False, default=False)
    password_set_at = Column(DateTime(timezone=True), nullable=True)


class LoginSession(TimestampMixin, Base):
    __tablename__ = "login_sessions"
    __table_args__ = (UniqueConstraint("session_token_hash", name="uq_login_session_token_hash"),)

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    session_token_hash = Column(String, nullable=False, unique=True)
    csrf_token = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    mfa_verified_at = Column(DateTime(timezone=True), nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)


class PasswordResetToken(TimestampMixin, Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),)

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)


class EmailVerificationToken(TimestampMixin, Base):
    __tablename__ = "email_verification_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_email_verification_token_hash"),)

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    attempt_id = Column(String, ForeignKey("assessment_attempts.id"), nullable=True)
    email = Column(String, nullable=False)
    purpose = Column(String, nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)


class MfaEnrollment(TimestampMixin, Base):
    __tablename__ = "mfa_enrollments"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    totp_secret = Column(String, nullable=False)
    recovery_codes_json = Column(JSON, nullable=False, default=list)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    disabled_at = Column(DateTime(timezone=True), nullable=True)


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
    preview_config_json = Column(JSON, nullable=False, default=dict)
    content_metadata_json = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)


class AssessmentAttempt(TimestampMixin, Base):
    __tablename__ = "assessment_attempts"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=True)
    track_version_id = Column(String, ForeignKey("track_versions.id"), nullable=False)
    candidate_label = Column(String, nullable=False, default="")
    invite_token = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default=AttemptStatus.pending.value)
    notes = Column(Text, nullable=False, default="")
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    opened_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class Session(TimestampMixin, Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    track_version_id = Column(String, ForeignKey("track_versions.id"), nullable=False)
    attempt_id = Column(String, ForeignKey("assessment_attempts.id"), nullable=True, unique=True)
    workspace_id = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default=SessionStatus.queued.value)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    runtime_failure_reason = Column(Text, nullable=True)
    environment_summary_json = Column(JSON, nullable=False, default=dict)
    telemetry_summary_json = Column(JSON, nullable=False, default=dict)
    integrity_summary_json = Column(JSON, nullable=False, default=dict)
    preview_summary_json = Column(JSON, nullable=False, default=dict)


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
    preview_summary_json = Column(JSON, nullable=False, default=dict)
    evidence_summary_json = Column(JSON, nullable=False, default=dict)
    visibility = Column(String, nullable=False, default=SubmissionVisibility.private.value)
    review_state = Column(String, nullable=False, default=ReviewState.pending_review.value)
    share_token = Column(String, nullable=False, unique=True)
    preview_share_token = Column(String, nullable=True, unique=True)
    artifact_manifest_uri = Column(String, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)


class Report(TimestampMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("submission_id", name="uq_report_submission"),)

    id = Column(String, primary_key=True)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False)
    visibility = Column(String, nullable=False, default=SubmissionVisibility.private.value)
    status = Column(String, nullable=False, default=ReportStatus.pending_review.value)
    candidate_summary_json = Column(JSON, nullable=False, default=dict)
    employer_summary_json = Column(JSON, nullable=False, default=dict)
    review_summary_json = Column(JSON, nullable=False, default=dict)
    is_portable = Column(Boolean, nullable=False, default=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_review_id = Column(String, ForeignKey("employer_reviews.id"), nullable=True)


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
    state = Column(String, nullable=False, default=ReviewDraftState.draft.value)
    escalation_state = Column(String, nullable=False, default=EscalationState.none.value)
    reviewer_annotations_json = Column(JSON, nullable=False, default=dict)
    draft_saved_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)


class ReviewerAssignment(TimestampMixin, Base):
    __tablename__ = "reviewer_assignments"

    id = Column(String, primary_key=True)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False)
    reviewer_id = Column(String, ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False, default=AssignmentStatus.queued.value)
    due_at = Column(DateTime(timezone=True), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class CalibrationRun(TimestampMixin, Base):
    __tablename__ = "calibration_runs"

    id = Column(String, primary_key=True)
    track_version_id = Column(String, ForeignKey("track_versions.id"), nullable=False)
    initiated_by = Column(String, ForeignKey("users.id"), nullable=False)
    notes = Column(Text, nullable=False, default="")
    sample_size = Column(Integer, nullable=False, default=0)
    rubric_version = Column(String, nullable=False, default="v1")
    result_summary_json = Column(JSON, nullable=False, default=dict)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class RuntimeJob(TimestampMixin, Base):
    __tablename__ = "runtime_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_runtime_job_idempotency"),)

    id = Column(String, primary_key=True)
    job_type = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    status = Column(String, nullable=False, default=RuntimeJobStatus.queued.value)
    idempotency_key = Column(String, nullable=True)
    attempts_count = Column(Integer, nullable=False, default=0)
    payload_json = Column(JSON, nullable=False, default=dict)
    result_json = Column(JSON, nullable=False, default=dict)
    error_text = Column(Text, nullable=True)
    available_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    max_attempts = Column(Integer, nullable=False, default=5)
    scheduled_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class AuditEvent(TimestampMixin, Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True)
    actor_id = Column(String, ForeignKey("users.id"), nullable=True)
    actor_label = Column(String, nullable=False, default="")
    event_type = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    payload_json = Column(JSON, nullable=False, default=dict)


class ReportAccess(TimestampMixin, Base):
    __tablename__ = "report_accesses"
    __table_args__ = (UniqueConstraint("token", name="uq_report_access_token"),)

    id = Column(String, primary_key=True)
    report_id = Column(String, ForeignKey("reports.id"), nullable=False)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=True)
    access_type = Column(String, nullable=False, default=ReportAccessType.report.value)
    token = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default=ReportAccessStatus.active.value)
    issued_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
