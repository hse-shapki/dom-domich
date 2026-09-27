"""Z08 initiative reminders and resident position.

Revision ID: b3e68a179c02
Revises: a7c41b0d55e8
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3e68a179c02"
down_revision = "a7c41b0d55e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "initiative_reminder_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("poll_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_key", sa.String(250), nullable=False),
        sa.Column("targets", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("house_id", "operation_key"),
        sa.ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
    )
    op.create_table(
        "initiative_reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("poll_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "outbox_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outbox_deliveries.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("poll_id", "resident_id", "number"),
        sa.ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        sa.ForeignKeyConstraint(
            ["poll_id", "resident_id"], ["poll_members.poll_id", "poll_members.resident_id"]
        ),
        sa.CheckConstraint("number > 0", name="initiative_reminder_number_positive"),
    )
    op.create_table(
        "initiative_decisions",
        sa.Column("poll_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initiative_revision", sa.Integer(), nullable=False),
        sa.Column("poll_version", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_revision", sa.String(100), nullable=False),
        sa.Column("demo", sa.Boolean(), nullable=False),
        sa.Column("operation_key", sa.String(250), nullable=False),
        sa.UniqueConstraint("house_id", "operation_key"),
        sa.ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        sa.ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        sa.ForeignKeyConstraint(
            ["case_id", "initiative_revision"],
            ["initiative_revisions.case_id", "initiative_revisions.revision"],
        ),
    )


def downgrade() -> None:
    op.drop_table("initiative_decisions")
    op.drop_table("initiative_reminders")
    op.drop_table("initiative_reminder_batches")
