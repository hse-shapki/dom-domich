"""durable scheduled jobs

Revision ID: b8106bc9ac21
Revises: a389e0219fbc
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8106bc9ac21"
down_revision = "a389e0219fbc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id"), nullable=False
        ),
        sa.Column("operation_key", sa.String(250), nullable=False),
        sa.Column("event_name", sa.String(80), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
        sa.UniqueConstraint("house_id", "operation_key"),
    )
    op.create_index("ix_scheduled_jobs_due", "scheduled_jobs", ["status", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_jobs_due", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")
