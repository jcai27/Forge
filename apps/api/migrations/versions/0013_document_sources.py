"""Which stored pages a production document's text was read from."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "document_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("parts", sa.JSON(), nullable=False),
        sa.UniqueConstraint("org_id", "text_hash"),
    )
    op.create_index("ix_document_sources_org_id", "document_sources", ["org_id"])


def downgrade():
    op.drop_index("ix_document_sources_org_id", table_name="document_sources")
    op.drop_table("document_sources")
