"""Z09 immutable document snapshots and PDF metadata.

Revision ID: c9ad4420e123
Revises: b3e68a179c02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c9ad4420e123"
down_revision = "b3e68a179c02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audience_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("poll_id", postgresql.UUID(as_uuid=True)),
        sa.Column("request_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "recipient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("residents.id"),
            nullable=False,
        ),
        sa.Column("operation_key", sa.String(250), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("template_revision", sa.String(100), nullable=False),
        sa.Column("snapshot_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("file_key", postgresql.UUID(as_uuid=True)),
        sa.Column("file_sha256", sa.String(64)),
        sa.Column("file_mime_type", sa.String(100)),
        sa.Column("file_size_bytes", sa.Integer()),
        sa.Column("file_retain_until", sa.DateTime(timezone=True)),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
        sa.UniqueConstraint("house_id", "operation_key"),
        sa.ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        sa.ForeignKeyConstraint(
            ["audience_id", "house_id"],
            ["audience_snapshots.id", "audience_snapshots.house_id"],
        ),
        sa.ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        sa.ForeignKeyConstraint(["request_id", "house_id"], ["requests.id", "requests.house_id"]),
        sa.CheckConstraint("attempts >= 0", name="document_attempts_nonnegative"),
    )
    op.create_index("ix_documents_queue", "documents", ["status", "lease_until", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_queue", table_name="documents")
    op.drop_table("documents")
