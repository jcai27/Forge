"""Customer workspaces: the kind of a workspace, and a customer's operations, channels and documents."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def owned(name, *columns):
    op.create_table(
        name,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        *columns,
    )
    op.create_index(f"ix_{name}_org_id", name, ["org_id"])


def upgrade():
    op.add_column("organizations", sa.Column("kind", sa.String(20), nullable=False, server_default="builder"))
    op.add_column("organizations", sa.Column("parent_org_id", sa.String(36), nullable=True))
    op.create_index("ix_organizations_parent_org_id", "organizations", ["parent_org_id"])
    owned(
        "portal_operations",
        sa.Column("deployment_id", sa.String(36), sa.ForeignKey("deployment_versions.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("document_field", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
    )
    op.create_index("ix_portal_operations_deployment_id", "portal_operations", ["deployment_id"])
    owned(
        "portal_channels",
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("portal_operations.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cursor", sa.JSON(), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(300), nullable=True),
    )
    op.create_index("ix_portal_channels_operation_id", "portal_channels", ["operation_id"])
    op.create_index("ix_portal_channels_next_check_at", "portal_channels", ["next_check_at"])
    owned(
        "portal_documents",
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("portal_operations.id"), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("sender", sa.String(320), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("corrected", sa.JSON(), nullable=True),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("deliveries", sa.JSON(), nullable=False),
        sa.UniqueConstraint("operation_id", "content_hash"),
    )
    op.create_index("ix_portal_documents_operation_id", "portal_documents", ["operation_id"])
    op.create_index("ix_portal_documents_status", "portal_documents", ["status"])


def downgrade():
    for name in ("portal_documents", "portal_channels", "portal_operations"):
        op.drop_table(name)
    op.drop_index("ix_organizations_parent_org_id", table_name="organizations")
    op.drop_column("organizations", "parent_org_id")
    op.drop_column("organizations", "kind")
