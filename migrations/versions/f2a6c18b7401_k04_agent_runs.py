"""K04 durable agent runs and pending questions.

Revision ID: f2a6c18b7401
Revises: e17d65a0f2c8
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f2a6c18b7401"
down_revision = "e17d65a0f2c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id"), nullable=False
        ),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True)),
        sa.Column("case_version", sa.Integer()),
        sa.Column("pending_question_id", postgresql.UUID(as_uuid=True)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_revision", sa.String(200)),
        sa.Column("prompt_revision", sa.String(100)),
        sa.UniqueConstraint("id", "house_id"),
        sa.UniqueConstraint("house_id", "event_id"),
    )
    op.create_index("ix_agent_runs_house_case", "agent_runs", ["house_id", "case_id", "created_at"])
    op.create_table(
        "pending_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "house_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("houses.id"), nullable=False
        ),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("residents.id"), nullable=False
        ),
        sa.Column("expected_case_version", sa.Integer(), nullable=False),
        sa.Column("requested_field", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("answered_event_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_index(
        "uq_pending_questions_open_actor_case",
        "pending_questions",
        ["house_id", "case_id", "actor_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_pending_questions_expiry", "pending_questions", ["status", "expires_at"])
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("house_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("outcome", sa.String(100), nullable=False),
        sa.Column("entity_version", sa.Integer()),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id", "house_id"], ["agent_runs.id", "agent_runs.house_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("run_id", "sequence"),
    )


def downgrade() -> None:
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_pending_questions_expiry", table_name="pending_questions")
    op.drop_index("uq_pending_questions_open_actor_case", table_name="pending_questions")
    op.drop_table("pending_questions")
    op.drop_index("ix_agent_runs_house_case", table_name="agent_runs")
    op.drop_table("agent_runs")
