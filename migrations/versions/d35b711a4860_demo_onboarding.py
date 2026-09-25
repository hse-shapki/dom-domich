"""demo invitations and selected house

Revision ID: d35b711a4860
Revises: c127a1f42d63
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d35b711a4860"
down_revision = "c127a1f42d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "residents",
        sa.Column("active_house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id")),
    )
    op.create_table(
        "demo_invitations",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column(
            "residency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("residencies.id"),
            nullable=False,
        ),
        sa.Column(
            "house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_demo_invitations_residency", "demo_invitations", ["residency_id"])


def downgrade() -> None:
    op.drop_index("ix_demo_invitations_residency", table_name="demo_invitations")
    op.drop_table("demo_invitations")
    op.drop_column("residents", "active_house_id")
