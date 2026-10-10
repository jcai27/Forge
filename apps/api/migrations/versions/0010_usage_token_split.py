"""Input and output tokens recorded separately, so usage can be priced per model."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("usage_records", sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("usage_records", sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("usage_records", "output_tokens")
    op.drop_column("usage_records", "input_tokens")
