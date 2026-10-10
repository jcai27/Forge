"""Cached input tokens on usage records, and the dataset an evaluation case came from."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("usage_records", sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("evaluation_cases", sa.Column("dataset_id", sa.String(36), nullable=True))
    op.create_index("ix_evaluation_cases_dataset_id", "evaluation_cases", ["dataset_id"])


def downgrade():
    op.drop_index("ix_evaluation_cases_dataset_id", table_name="evaluation_cases")
    op.drop_column("evaluation_cases", "dataset_id")
    op.drop_column("usage_records", "cached_tokens")
