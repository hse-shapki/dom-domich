"""inbox worker leases

Revision ID: d18192e6a161
Revises: 916f93cc4c0a
Create Date: 2026-09-25 14:20:16.645112
"""

import sqlalchemy as sa
from alembic import op

revision = "d18192e6a161"
down_revision = "916f93cc4c0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inbox_events", sa.Column("available_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "inbox_events", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("inbox_events", sa.Column("lease_owner", sa.String(length=100), nullable=True))
    op.add_column(
        "inbox_events", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE inbox_events SET available_at = received_at")
    op.alter_column("inbox_events", "available_at", nullable=False)


def downgrade() -> None:
    op.drop_column("inbox_events", "lease_until")
    op.drop_column("inbox_events", "lease_owner")
    op.drop_column("inbox_events", "attempts")
    op.drop_column("inbox_events", "available_at")
