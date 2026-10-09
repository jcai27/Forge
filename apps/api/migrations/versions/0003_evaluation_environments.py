"""Replay/read-only evaluation environments and recorded grading rubrics."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evaluation_cases", sa.Column("environment", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("evaluation_cases", sa.Column("rubric", sa.JSON(), nullable=True))
    if op.get_bind().dialect.name == "sqlite":
        # SQLite supports an inline nullable REFERENCES column. Rebuilding this table
        # would fail with existing evaluation_results while foreign keys remain enabled.
        op.execute("ALTER TABLE evaluation_cases ADD COLUMN authorized_by VARCHAR(36) REFERENCES users (id)")
    else:
        op.add_column("evaluation_cases", sa.Column("authorized_by", sa.String(36), nullable=True))
        op.create_foreign_key("fk_evaluation_case_authorizer", "evaluation_cases", "users", ["authorized_by"], ["id"])


def downgrade():
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_evaluation_case_authorizer", "evaluation_cases", type_="foreignkey")
    op.drop_column("evaluation_cases", "authorized_by")
    op.drop_column("evaluation_cases", "rubric")
    op.drop_column("evaluation_cases", "environment")
