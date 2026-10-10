"""Retain uncertain provider charges separately from observed usage."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("usage_records", sa.Column("status", sa.String(30), nullable=False, server_default="recorded"))
    op.add_column("usage_records", sa.Column("reserved_cost", sa.Float(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("usage_records") as batch:
        batch.drop_column("reserved_cost")
        batch.drop_column("status")
