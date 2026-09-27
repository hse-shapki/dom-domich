"""Z07 callback buttons stored with outbox intent.

Revision ID: 0a7b6c5d4e3f
Revises: f1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0a7b6c5d4e3f"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox_deliveries",
        sa.Column("buttons", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("outbox_deliveries", "buttons")
