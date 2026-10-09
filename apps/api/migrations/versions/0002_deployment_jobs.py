"""Durable invocation jobs, deployment triggers and lifetime usage."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deployment_versions", sa.Column("spent", sa.Float(), nullable=False, server_default="0"))
    op.add_column("deployment_versions", sa.Column("reserved", sa.Float(), nullable=False, server_default="0"))
    op.create_table(
        "runtime_jobs",
        sa.Column(
            "invocation_id", sa.String(36), sa.ForeignKey("deployment_invocations.id"), nullable=False, unique=True
        ),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("reservation", sa.Float(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_runtime_jobs_org_id", "runtime_jobs", ["org_id"])
    op.create_index("ix_runtime_jobs_state", "runtime_jobs", ["state"])
    op.create_index("ix_runtime_jobs_lease_until", "runtime_jobs", ["lease_until"])
    op.create_table(
        "deployment_triggers",
        sa.Column("deployment_id", sa.String(36), sa.ForeignKey("deployment_versions.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("interval_seconds", sa.Integer()),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("last_error", sa.String(100)),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_deployment_triggers_org_id", "deployment_triggers", ["org_id"])
    op.create_index("ix_deployment_triggers_deployment_id", "deployment_triggers", ["deployment_id"])
    op.create_index("ix_deployment_triggers_next_run_at", "deployment_triggers", ["next_run_at"])


def downgrade():
    op.drop_table("deployment_triggers")
    op.drop_table("runtime_jobs")
    op.drop_column("deployment_versions", "reserved")
    op.drop_column("deployment_versions", "spent")
