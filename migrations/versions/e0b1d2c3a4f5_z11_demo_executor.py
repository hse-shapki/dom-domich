"""Z11 durable demo executor.

Revision ID: e0b1d2c3a4f5
Revises: c9ad4420e123
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e0b1d2c3a4f5"
down_revision = "c9ad4420e123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_executor_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_key", sa.String(250), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registration_number", sa.String(100)),
        sa.Column("registered_at", sa.DateTime(timezone=True)),
        sa.Column("status_updated_at", sa.DateTime(timezone=True)),
        sa.Column("processed_event_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("house_id", "operation_key"),
        sa.UniqueConstraint("house_id", "request_id"),
        sa.ForeignKeyConstraint(["request_id", "house_id"], ["requests.id", "requests.house_id"]),
        sa.CheckConstraint("draft_revision > 0", name="demo_executor_draft_revision_positive"),
    )


def downgrade() -> None:
    op.drop_table("demo_executor_operations")
