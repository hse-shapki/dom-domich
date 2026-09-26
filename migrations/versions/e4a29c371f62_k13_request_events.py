"""K13 trusted executor status and document links.

Revision ID: e4a29c371f62
Revises: c1e51e6219d7
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e4a29c371f62"
down_revision = "c1e51e6219d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("external_status", sa.String(40)))
    op.add_column(
        "requests", sa.Column("external_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("requests", sa.Column("external_status_updated_at", sa.DateTime(timezone=True)))
    op.add_column("requests", sa.Column("document_id", postgresql.UUID(as_uuid=True)))
    op.add_column("requests", sa.Column("document_snapshot_hash", sa.String(64)))
    op.add_column("requests", sa.Column("document_file_key", postgresql.UUID(as_uuid=True)))
    op.alter_column("requests", "external_version", server_default=None)


def downgrade() -> None:
    op.drop_column("requests", "document_file_key")
    op.drop_column("requests", "document_snapshot_hash")
    op.drop_column("requests", "document_id")
    op.drop_column("requests", "external_status_updated_at")
    op.drop_column("requests", "external_version")
    op.drop_column("requests", "external_status")
