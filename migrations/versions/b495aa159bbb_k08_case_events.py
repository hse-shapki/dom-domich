"""K08 case messages, evidence references, events and operation keys.

Revision ID: b495aa159bbb
Revises: a35d41505be3
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b495aa159bbb"
down_revision = "a35d41505be3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_messages",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id")),
        sa.Column("relation", sa.String(30), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("case_id", "message_id"),
        sa.ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
    )
    op.create_index("ix_case_messages_house_message", "case_messages", ["house_id", "message_id"])
    op.create_table(
        "case_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id")),
        sa.Column("source_ref", sa.String(300), nullable=False),
        sa.Column("file_key", sa.String(500)),
        sa.Column("assessment", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        sa.UniqueConstraint("case_id", "source_ref"),
    )
    op.create_table(
        "case_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("before_version", sa.Integer()),
        sa.Column("after_version", sa.Integer(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id")),
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True)),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("facts", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        sa.UniqueConstraint("house_id", "operation_id"),
    )
    op.create_table(
        "case_operations",
        sa.Column(
            "house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id"), nullable=False
        ),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command_hash", sa.String(64), nullable=False),
        sa.Column("result_view", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("house_id", "operation_id"),
        sa.ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
    )


def downgrade() -> None:
    op.drop_table("case_operations")
    op.drop_table("case_events")
    op.drop_table("case_evidence")
    op.drop_index("ix_case_messages_house_message", table_name="case_messages")
    op.drop_table("case_messages")
