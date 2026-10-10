from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from factory.db import Base, now, uid


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)


class Owned(Identity):
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)


class Organization(Identity, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200))


class User(Identity, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)


class Membership(Identity, Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(30), default="admin")


class OrganizationInvitation(Owned, Base):
    __tablename__ = "organization_invitations"
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class Project(Owned, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")


class AgentRecord(Owned, Base):
    __tablename__ = "agent_specs"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    request: Mapped[str] = mapped_column(Text)
    template: Mapped[str] = mapped_column(String(40))
    best_version_id: Mapped[str | None] = mapped_column(String(36))


class AgentVersion(Owned, Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "number"),)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_specs.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSON)
    hypothesis: Mapped[str] = mapped_column(Text, default="Initial candidate")
    approved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class Integration(Identity, Base):
    __tablename__ = "integrations"
    kind: Mapped[str] = mapped_column(String(40), unique=True)
    manifest: Mapped[dict] = mapped_column(JSON)


class Connection(Owned, Base):
    __tablename__ = "integration_connections"
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted_secret: Mapped[str] = mapped_column(Text, default="")
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="setup_required")


class DataSource(Owned, Base):
    __tablename__ = "data_sources"
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    schema: Mapped[dict] = mapped_column(JSON)
    model_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    records: Mapped[list] = mapped_column(JSON, default=list)


class ToolDefinition(Owned, Base):
    __tablename__ = "tool_definitions"
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id"))
    name: Mapped[str] = mapped_column(String(100))
    definition: Mapped[dict] = mapped_column(JSON)
    write: Mapped[bool] = mapped_column(Boolean, default=False)


class AgentTool(Identity, Base):
    __tablename__ = "agent_tools"
    __table_args__ = (UniqueConstraint("version_id", "tool_id"),)
    version_id: Mapped[str] = mapped_column(ForeignKey("agent_versions.id"))
    tool_id: Mapped[str] = mapped_column(ForeignKey("tool_definitions.id"))


class BuildJob(Owned, Base):
    __tablename__ = "build_jobs"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_specs.id"), index=True)
    state: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    budget: Mapped[dict] = mapped_column(JSON)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    spent: Mapped[float] = mapped_column(Float, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class BuildIteration(Owned, Base):
    __tablename__ = "build_iterations"
    __table_args__ = (UniqueConstraint("job_id", "number"),)
    job_id: Mapped[str] = mapped_column(ForeignKey("build_jobs.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    version_id: Mapped[str] = mapped_column(ForeignKey("agent_versions.id"))
    scorecard: Mapped[dict] = mapped_column(JSON)
    diagnosis: Mapped[dict] = mapped_column(JSON)
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)


class EvaluationSuite(Owned, Base):
    __tablename__ = "evaluation_suites"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_specs.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))


class EvaluationCase(Owned, Base):
    __tablename__ = "evaluation_cases"
    suite_id: Mapped[str] = mapped_column(ForeignKey("evaluation_suites.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    split: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(30), default="synthetic")
    input: Mapped[dict] = mapped_column(JSON)
    assertions: Mapped[list] = mapped_column(JSON)
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    trials: Mapped[int] = mapped_column(Integer, default=1)
    environment: Mapped[dict] = mapped_column(JSON, default=dict)
    rubric: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    authorized_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class EvaluationRun(Owned, Base):
    __tablename__ = "evaluation_runs"
    version_id: Mapped[str] = mapped_column(ForeignKey("agent_versions.id"), index=True)
    suite_id: Mapped[str] = mapped_column(ForeignKey("evaluation_suites.id"))
    status: Mapped[str] = mapped_column(String(30), default="running")
    scorecard: Mapped[dict] = mapped_column(JSON, default=dict)


class ExecutionRun(Owned, Base):
    __tablename__ = "execution_runs"
    version_id: Mapped[str] = mapped_column(ForeignKey("agent_versions.id"), index=True)
    mode: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="running")
    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class EvaluationResult(Owned, Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (UniqueConstraint("evaluation_run_id", "case_id", "trial"),)
    evaluation_run_id: Mapped[str] = mapped_column(ForeignKey("evaluation_runs.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("evaluation_cases.id"))
    execution_id: Mapped[str] = mapped_column(ForeignKey("execution_runs.id"))
    trial: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[bool] = mapped_column(Boolean)
    checks: Mapped[list] = mapped_column(JSON)
    failures: Mapped[list] = mapped_column(JSON)


class ExecutionEvent(Owned, Base):
    __tablename__ = "execution_events"
    sequence: Mapped[int] = mapped_column(Integer, autoincrement=True, unique=True, nullable=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("execution_runs.id"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("build_jobs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)


class Deployment(Owned, Base):
    __tablename__ = "deployment_versions"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_specs.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("agent_versions.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    spent: Mapped[float] = mapped_column(Float, default=0)
    reserved: Mapped[float] = mapped_column(Float, default=0)


class Invocation(Owned, Base):
    __tablename__ = "deployment_invocations"
    __table_args__ = (UniqueConstraint("deployment_id", "idempotency_key"),)
    deployment_id: Mapped[str] = mapped_column(ForeignKey("deployment_versions.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    run_id: Mapped[str] = mapped_column(ForeignKey("execution_runs.id"))


class Approval(Owned, Base):
    __tablename__ = "approval_requests"
    run_id: Mapped[str] = mapped_column(ForeignKey("execution_runs.id"), index=True)
    action: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class AuditEvent(Owned, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class UsageRecord(Owned, Base):
    __tablename__ = "usage_records"
    run_id: Mapped[str | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("build_jobs.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(100), default="execution")
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(30), default="recorded")
    reserved_cost: Mapped[float] = mapped_column(Float, default=0)


class SecretRedactionEntry(Owned, Base):
    """Retired ciphertext used only for filtering historical data, never authentication."""

    __tablename__ = "secret_redaction_entries"
    connection_id: Mapped[str] = mapped_column(ForeignKey("integration_connections.id"), unique=True)
    encrypted_secret: Mapped[str] = mapped_column(Text)


class BusinessRecord(Owned, Base):
    __tablename__ = "business_records"
    __table_args__ = (UniqueConstraint("org_id", "collection", "key"),)
    collection: Mapped[str] = mapped_column(String(50))
    key: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict] = mapped_column(JSON)


class RuntimeJob(Owned, Base):
    __tablename__ = "runtime_jobs"
    invocation_id: Mapped[str] = mapped_column(ForeignKey("deployment_invocations.id"), unique=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    state: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    reservation: Mapped[float] = mapped_column(Float, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), index=True)
    error: Mapped[str | None] = mapped_column(Text)


class DeploymentTrigger(Owned, Base):
    __tablename__ = "deployment_triggers"
    deployment_id: Mapped[str] = mapped_column(ForeignKey("deployment_versions.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    next_run_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), index=True)
    encrypted_secret: Mapped[str] = mapped_column(Text, default="")
    last_error: Mapped[str | None] = mapped_column(String(100))
