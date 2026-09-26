"""K10 versioned requests and idempotent operation snapshots.

Revision ID: c1e51e6219d7
Revises: b495aa159bbb
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c1e51e6219d7"
down_revision = "b495aa159bbb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("responsible_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rule_versions.id"),
            nullable=False,
        ),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("approved_version", sa.Integer()),
        sa.Column("approval_actor", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id")),
        sa.Column("submit_operation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("executor_operation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("registration_id", sa.String(100)),
        sa.Column("registered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("id", "house_id"),
        sa.ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
    )
    op.create_index("ix_requests_house_case", "requests", ["house_id", "case_id"])
    op.create_table(
        "request_operations",
        sa.Column(
            "house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id"), nullable=False
        ),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command_hash", sa.String(64), nullable=False),
        sa.Column("result_view", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("house_id", "operation_id"),
        sa.ForeignKeyConstraint(["request_id", "house_id"], ["requests.id", "requests.house_id"]),
    )


def downgrade() -> None:
    op.drop_table("request_operations")
    op.drop_index("ix_requests_house_case", table_name="requests")
    op.drop_table("requests")
