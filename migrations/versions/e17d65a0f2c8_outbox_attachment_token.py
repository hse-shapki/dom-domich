"""persist uploaded MAX file token

Revision ID: e17d65a0f2c8
Revises: d35b711a4860
"""

import sqlalchemy as sa
from alembic import op

revision = "e17d65a0f2c8"
down_revision = "d35b711a4860"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox_deliveries", sa.Column("attachment_token", sa.String(500)))
    op.execute(
        "UPDATE outbox_deliveries SET status = 'pending' WHERE status = 'waiting_attachment'"
    )


def downgrade() -> None:
    op.drop_column("outbox_deliveries", "attachment_token")
