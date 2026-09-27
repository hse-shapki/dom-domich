"""Z04 durable poll state and answer history.

Revision ID: 9d20b8a6c743
Revises: 63a9d1e4bc02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9d20b8a6c743"
down_revision = "63a9d1e4bc02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "polls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audience_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_key", sa.String(250), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("policy", postgresql.JSONB(), nullable=False),
        sa.Column("subject_revision", sa.Integer(), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(40)),
        sa.Column("threshold_emitted", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("id", "house_id"),
        sa.UniqueConstraint("id", "audience_id"),
        sa.UniqueConstraint("house_id", "operation_key"),
        sa.UniqueConstraint("case_id", "audience_id", "kind", "subject_revision"),
        sa.ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        sa.ForeignKeyConstraint(
            ["audience_id", "house_id"],
            ["audience_snapshots.id", "audience_snapshots.house_id"],
        ),
        sa.CheckConstraint("version > 0 AND subject_revision > 0", name="poll_positive_versions"),
        sa.CheckConstraint("closes_at > opens_at", name="poll_positive_window"),
    )
    op.create_table(
        "poll_members",
        sa.Column("poll_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audience_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        sa.ForeignKeyConstraint(["poll_id", "audience_id"], ["polls.id", "polls.audience_id"]),
        sa.ForeignKeyConstraint(
            ["audience_id", "resident_id"],
            ["audience_members.audience_id", "audience_members.resident_id"],
        ),
    )
    op.create_table(
        "poll_answers",
        sa.Column("poll_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("choice", sa.String(10), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["poll_id", "resident_id"], ["poll_members.poll_id", "poll_members.resident_id"]
        ),
        sa.CheckConstraint("revision > 0", name="poll_answer_revision_positive"),
    )
    op.create_table(
        "poll_answer_history",
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("poll_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("choice", sa.String(10), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("source_event_id"),
        sa.UniqueConstraint("poll_id", "resident_id", "revision"),
        sa.ForeignKeyConstraint(
            ["poll_id", "resident_id"], ["poll_members.poll_id", "poll_members.resident_id"]
        ),
        sa.CheckConstraint("revision > 0", name="poll_history_revision_positive"),
    )


def downgrade() -> None:
    op.drop_table("poll_answer_history")
    op.drop_table("poll_answers")
    op.drop_table("poll_members")
    op.drop_table("polls")
