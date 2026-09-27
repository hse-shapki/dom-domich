"""Z12/13 durable resolution checks.

Revision ID: f1a2b3c4d5e6
Revises: e0b1d2c3a4f5
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f1a2b3c4d5e6"
down_revision = "e0b1d2c3a4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resolution_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_audience_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("poll_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_version_at_start", sa.Integer(), nullable=False),
        sa.Column("done_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_operation_key", sa.String(250), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("poll_version_at_decision", sa.Integer()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("finalize_operation_key", sa.String(250)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("house_id", "start_operation_key"),
        sa.UniqueConstraint("house_id", "done_event_id"),
        sa.UniqueConstraint("house_id", "poll_id"),
        sa.ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        sa.ForeignKeyConstraint(["request_id", "house_id"], ["requests.id", "requests.house_id"]),
        sa.ForeignKeyConstraint(
            ["original_audience_id", "house_id"],
            ["audience_snapshots.id", "audience_snapshots.house_id"],
        ),
        sa.ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        sa.CheckConstraint("version > 0", name="resolution_version_positive"),
    )


def downgrade() -> None:
    op.drop_table("resolution_checks")
