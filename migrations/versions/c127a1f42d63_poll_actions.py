"""opaque poll actions

Revision ID: c127a1f42d63
Revises: b8106bc9ac21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c127a1f42d63"
down_revision = "b8106bc9ac21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "poll_actions",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column("poll_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id"), nullable=False
        ),
        sa.Column("audience_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_revision", sa.Integer(), nullable=False),
        sa.Column("choice", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "bound_resident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id")
        ),
        sa.Column("revoked", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_poll_actions_poll_id", "poll_actions", ["poll_id"])


def downgrade() -> None:
    op.drop_index("ix_poll_actions_poll_id", table_name="poll_actions")
    op.drop_table("poll_actions")
