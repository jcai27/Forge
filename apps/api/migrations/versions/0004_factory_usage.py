"""Account factory role calls independently of execution runs."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("usage_records") as batch:
        batch.alter_column("run_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("job_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("role", sa.String(100), nullable=False, server_default="execution"))
        batch.create_foreign_key("fk_usage_build_job", "build_jobs", ["job_id"], ["id"])


def downgrade():
    # Factory records have no execution FK and cannot be represented by the old schema.
    op.execute("DELETE FROM usage_records WHERE run_id IS NULL")
    with op.batch_alter_table("usage_records") as batch:
        batch.drop_constraint("fk_usage_build_job", type_="foreignkey")
        batch.drop_column("role")
        batch.drop_column("job_id")
        batch.alter_column("run_id", existing_type=sa.String(36), nullable=False)
