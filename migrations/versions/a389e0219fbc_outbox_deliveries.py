"""durable outbound deliveries

Revision ID: a389e0219fbc
Revises: d18192e6a161
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a389e0219fbc"
down_revision = "d18192e6a161"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id"), nullable=False
        ),
        sa.Column("operation_key", sa.String(250), nullable=False),
        sa.Column("text", sa.String(4000), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id")),
        sa.Column("chat_id", sa.String(40)),
        sa.Column("edit_key", sa.String(250)),
        sa.Column("file_key", postgresql.UUID(as_uuid=True)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("max_message_id", sa.String(100)),
        sa.Column("error_code", sa.String(100)),
        sa.UniqueConstraint("house_id", "operation_key"),
        sa.CheckConstraint(
            "(recipient_id IS NULL) <> (chat_id IS NULL)", name="outbox_exactly_one_target"
        ),
    )
    op.create_index("ix_outbox_deliveries_due", "outbox_deliveries", ["status", "available_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_deliveries_due", table_name="outbox_deliveries")
    op.drop_table("outbox_deliveries")
