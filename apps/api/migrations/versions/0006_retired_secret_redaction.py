"""Keep retired ciphertext for historical secret filtering, never connector dispatch."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "secret_redaction_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("integration_connections.id"), nullable=False, unique=True),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
    )
    op.create_index("ix_secret_redaction_entries_org_id", "secret_redaction_entries", ["org_id"])


def downgrade():
    op.drop_table("secret_redaction_entries")
