from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
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
    # "builder": a workspace where agents are built. "customer": a workspace a builder opened for a
    # customer, who works in the portal only. A customer workspace is a tenant of its own.
    kind: Mapped[str] = mapped_column(String(20), default="builder", server_default="builder")
    # The builder workspace that opened a customer workspace.
    parent_org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


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
    # Set only when someone has stated that the task can be judged without example data.
    no_data_reason: Mapped[str] = mapped_column(Text, default="", server_default="")


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


class ConnectionProposal(Owned, Base):
    """A drafted connection. It holds no credential and grants nothing until an administrator approves it."""

    __tablename__ = "connection_proposals"
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agent_specs.id"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("build_jobs.id"))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    rationale: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list] = mapped_column(JSON, default=list)
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(String(30), default="manual")
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    connection_id: Mapped[str | None] = mapped_column(ForeignKey("integration_connections.id"))


class ContextDocument(Owned, Base):
    """A document about how the customer operates. Read by the builder, never by the deployed agent."""

    __tablename__ = "context_documents"
    __table_args__ = (UniqueConstraint("agent_id", "name"),)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_specs.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    chars: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))


class DocumentReading(Owned, Base):
    """The text a model read from one scanned page or photo, kept so a page is paid for once."""

    __tablename__ = "document_readings"
    __table_args__ = (UniqueConstraint("org_id", "content_hash"),)
    # Of the page image, the model and the reading instructions together.
    content_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)


class DocumentPage(Owned, Base):
    """The image of one scanned page of an example, kept so the page can be read again differently."""

    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("org_id", "content_hash"),)
    content_hash: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(40))
    data: Mapped[bytes] = mapped_column(LargeBinary)


class DocumentSource(Owned, Base):
    """The pages a production request's document text was read from, so a run can show the scan.

    Kept only when the caller asks. Found again by a hash of the text, which is what a run holds.
    """

    __tablename__ = "document_sources"
    __table_args__ = (UniqueConstraint("org_id", "text_hash"),)
    text_hash: Mapped[str] = mapped_column(String(64))
    parts: Mapped[list] = mapped_column(JSON)


class Dataset(Owned, Base):
    """Where a set of evaluation cases came from. The rows themselves live on as cases."""

    __tablename__ = "datasets"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_specs.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    origin: Mapped[str] = mapped_column(String(30), default="upload")
    source_url: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    rows: Mapped[int] = mapped_column(Integer)
    mapping: Mapped[dict] = mapped_column(JSON)
    profile: Mapped[dict] = mapped_column(JSON)


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
    # Set when the case came from an attached dataset, so the dataset can be removed with its cases.
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # For a request field read from a document with scanned pages: its pages in order, each
    # {"text": ...} or {"page": hash of a DocumentPage}. Lets a version with its own reading
    # settings have the pages read again.
    documents: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


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
    # The split of tokens, where the provider reported one. Output includes reasoning.
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Part of input_tokens the provider served from its prompt cache.
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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


class Operation(Owned, Base):
    """A deployed agent a customer workspace uses: what its people see as one kind of work.

    Documents arriving for it are processed as the member in actor_id, who must still hold write
    access, exactly as a deployment trigger runs as the person who set it up.
    """

    __tablename__ = "portal_operations"
    deployment_id: Mapped[str] = mapped_column(ForeignKey("deployment_versions.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    # The request field the document's text goes into.
    document_field: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Where the agent came from: the builder's workspace, agent and version.
    source: Mapped[dict] = mapped_column(JSON, default=dict)
    # What the documents of this operation are: "invoice", or "statement" (a supplier's list of
    # invoices, reconciled against the invoices received).
    kind: Mapped[str] = mapped_column(String(20), default="invoice", server_default="invoice")
    # The customer's own settings: whether clean documents are approved without a person, payment
    # terms, and how lines are coded to ledger accounts.
    settings: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class Channel(Owned, Base):
    """A way documents reach an operation, or results leave it.

    kind "mailbox": an IMAP mailbox that is checked for attachments. "inbound": an address other
    systems post files to, authorised by a key of which only the hash is kept. "webhook": a URL
    each result is posted to.
    """

    __tablename__ = "portal_channels"
    operation_id: Mapped[str] = mapped_column(ForeignKey("portal_operations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted_secret: Mapped[str] = mapped_column(Text, default="")
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # What a mailbox has been read up to, and when and how the last check went.
    cursor: Mapped[dict] = mapped_column(JSON, default=dict)
    next_check_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_checked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)


class InboxDocument(Owned, Base):
    """One document a customer workspace received, and what became of it."""

    __tablename__ = "portal_documents"
    __table_args__ = (UniqueConstraint("operation_id", "content_hash"),)
    operation_id: Mapped[str] = mapped_column(ForeignKey("portal_operations.id"), index=True)
    channel_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # "upload", "mailbox" or "inbound".
    source: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(300))
    sender: Mapped[str] = mapped_column(String(320), default="")
    # Of the file as received: the same file twice is one document.
    content_hash: Mapped[str] = mapped_column(String(64))
    # "processing", "processed", "failed".
    status: Mapped[str] = mapped_column(String(20), default="processing", index=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # The pages in order, each {"page": hash of its stored image} with "text" as well where the page
    # was typed. Enough to show the document and to put it through the agent again.
    pages: Mapped[list] = mapped_column(JSON, default=list)
    # The agent's answer, and the answer as a person corrected it, if anyone did.
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    corrected: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0)
    # How sending the result on went, per webhook channel id.
    deliveries: Mapped[dict] = mapped_column(JSON, default=dict)
    # Where a processed document stands: "review" (something needs a person), "ready" (nothing found,
    # waiting for approval), "approved", "exported" (sent to the books).
    stage: Mapped[str] = mapped_column(String(20), default="new", server_default="new", index=True)
    # What the automatic checks found, each {"kind", "message", ...}. Worked out in code.
    exceptions: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    export_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class ExportBatch(Owned, Base):
    """Approved documents sent to the books together, as one file in an accounting system's import format."""

    __tablename__ = "portal_exports"
    operation_id: Mapped[str] = mapped_column(ForeignKey("portal_operations.id"), index=True)
    format: Mapped[str] = mapped_column(String(30))
    created_by: Mapped[str] = mapped_column(String(36))
    documents: Mapped[int] = mapped_column(Integer)
    # The file as it was produced, so the same batch can be fetched again unchanged.
    content: Mapped[str] = mapped_column(Text)
