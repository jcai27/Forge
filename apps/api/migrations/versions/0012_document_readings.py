"""Scanned pages: the text read from each, the page images of examples, and which case fields they fill."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "document_readings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.UniqueConstraint("org_id", "content_hash"),
    )
    op.create_index("ix_document_readings_org_id", "document_readings", ["org_id"])
    op.create_table(
        "document_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(40), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("org_id", "content_hash"),
    )
    op.create_index("ix_document_pages_org_id", "document_pages", ["org_id"])
    op.add_column("evaluation_cases", sa.Column("documents", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("evaluation_cases", "documents")
    op.drop_index("ix_document_pages_org_id", table_name="document_pages")
    op.drop_table("document_pages")
    op.drop_index("ix_document_readings_org_id", table_name="document_readings")
    op.drop_table("document_readings")
