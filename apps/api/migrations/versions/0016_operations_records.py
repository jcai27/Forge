"""Records of a customer's operations outside its documents, for the operations pages."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "portal_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("area", sa.String(30), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("location", sa.String(200), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="sample"),
    )
    op.create_index("ix_portal_records_org_id", "portal_records", ["org_id"])
    op.create_index("ix_portal_records_area", "portal_records", ["area"])


def downgrade():
    op.drop_table("portal_records")
