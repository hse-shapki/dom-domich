"""Z03 durable audience snapshots.

Revision ID: 63a9d1e4bc02
Revises: e4a29c371f62
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "63a9d1e4bc02"
down_revision = "e4a29c371f62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audience_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id"), nullable=False
        ),
        sa.Column("operation_key", sa.String(250), nullable=False),
        sa.Column("scope_kind", sa.String(20), nullable=False),
        sa.Column("entrance", sa.Integer()),
        sa.Column("floor", sa.Integer()),
        sa.Column("riser_id", postgresql.UUID(as_uuid=True)),
        sa.Column("riser_kind", sa.String(40)),
        sa.Column("criteria_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "supersedes_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("audience_snapshots.id")
        ),
        sa.UniqueConstraint("id", "house_id"),
        sa.UniqueConstraint("house_id", "operation_key"),
        sa.UniqueConstraint("supersedes_id"),
        sa.CheckConstraint("criteria_revision > 0", name="audience_revision_positive"),
    )
    op.create_table(
        "audience_members",
        sa.Column("audience_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "resident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("residents.id"),
            primary_key=True,
        ),
        sa.Column("reachable_at_snapshot", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["audience_id", "house_id"],
            ["audience_snapshots.id", "audience_snapshots.house_id"],
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("audience_members")
    op.drop_table("audience_snapshots")
