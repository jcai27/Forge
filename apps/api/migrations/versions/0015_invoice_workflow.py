"""The invoice workflow on the customer side: stages, exceptions, approval, exports and operation settings."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("portal_operations", sa.Column("kind", sa.String(20), nullable=False, server_default="invoice"))
    op.add_column("portal_operations", sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("portal_documents", sa.Column("stage", sa.String(20), nullable=False, server_default="new"))
    op.add_column("portal_documents", sa.Column("exceptions", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("portal_documents", sa.Column("approved_by", sa.String(36), nullable=True))
    op.add_column("portal_documents", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("portal_documents", sa.Column("export_id", sa.String(36), nullable=True))
    op.create_index("ix_portal_documents_stage", "portal_documents", ["stage"])
    op.create_index("ix_portal_documents_export_id", "portal_documents", ["export_id"])
    op.create_table(
        "portal_exports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("portal_operations.id"), nullable=False),
        sa.Column("format", sa.String(30), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("documents", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
    )
    op.create_index("ix_portal_exports_org_id", "portal_exports", ["org_id"])
    op.create_index("ix_portal_exports_operation_id", "portal_exports", ["operation_id"])


def downgrade():
    op.drop_table("portal_exports")
    op.drop_index("ix_portal_documents_export_id", table_name="portal_documents")
    op.drop_index("ix_portal_documents_stage", table_name="portal_documents")
    for column in ("export_id", "approved_at", "approved_by", "exceptions", "stage"):
        op.drop_column("portal_documents", column)
    op.drop_column("portal_operations", "settings")
    op.drop_column("portal_operations", "kind")
