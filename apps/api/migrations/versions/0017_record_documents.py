"""The document an operations record was written from."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("portal_records", sa.Column("document_id", sa.String(36), nullable=True))
    op.create_index("ix_portal_records_document_id", "portal_records", ["document_id"])


def downgrade():
    op.drop_index("ix_portal_records_document_id", table_name="portal_records")
    op.drop_column("portal_records", "document_id")
