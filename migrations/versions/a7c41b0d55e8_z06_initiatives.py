"""Z06 immutable initiative revisions.

Revision ID: a7c41b0d55e8
Revises: 9d20b8a6c743
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7c41b0d55e8"
down_revision = "9d20b8a6c743"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "initiatives",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("residents.id"),
            nullable=False,
        ),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("case_id", "house_id"),
        sa.ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        sa.CheckConstraint(
            "case_version > 0 AND current_revision > 0", name="initiative_positive_versions"
        ),
    )
    op.create_table(
        "initiative_revisions",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("wording", sa.Text(), nullable=False),
        sa.Column("audience_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("poll_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id", "house_id"], ["initiatives.case_id", "initiatives.house_id"]
        ),
        sa.ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        sa.ForeignKeyConstraint(
            ["audience_id", "house_id"],
            ["audience_snapshots.id", "audience_snapshots.house_id"],
        ),
        sa.UniqueConstraint("poll_id"),
        sa.CheckConstraint("revision > 0", name="initiative_revision_positive"),
    )
    op.create_table(
        "initiative_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_key", sa.String(250), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("house_id", "operation_key"),
        sa.ForeignKeyConstraint(
            ["case_id", "house_id"], ["initiatives.case_id", "initiatives.house_id"]
        ),
        sa.CheckConstraint("revision > 0", name="initiative_operation_revision_positive"),
    )


def downgrade() -> None:
    op.drop_table("initiative_operations")
    op.drop_table("initiative_revisions")
    op.drop_table("initiatives")
