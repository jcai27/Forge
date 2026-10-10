"""Drafted connections awaiting administrator review; no credential is ever stored here."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "connection_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent_specs.id")),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("build_jobs.id")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("origin", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("integration_connections.id")),
    )
    op.create_index("ix_connection_proposals_org_id", "connection_proposals", ["org_id"])
    op.create_index("ix_connection_proposals_agent_id", "connection_proposals", ["agent_id"])


def downgrade():
    op.drop_table("connection_proposals")
