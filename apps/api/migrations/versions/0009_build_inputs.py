"""Build inputs: business context documents, datasets and the no-data statement."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_specs", sa.Column("no_data_reason", sa.Text(), nullable=False, server_default=""))
    op.create_table(
        "context_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent_specs.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("agent_id", "name"),
    )
    op.create_index("ix_context_documents_org_id", "context_documents", ["org_id"])
    op.create_index("ix_context_documents_agent_id", "context_documents", ["agent_id"])
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent_specs.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("origin", sa.String(30), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("mapping", sa.JSON(), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
    )
    op.create_index("ix_datasets_org_id", "datasets", ["org_id"])
    op.create_index("ix_datasets_agent_id", "datasets", ["agent_id"])


def downgrade():
    op.drop_table("datasets")
    op.drop_table("context_documents")
    op.drop_column("agent_specs", "no_data_reason")
