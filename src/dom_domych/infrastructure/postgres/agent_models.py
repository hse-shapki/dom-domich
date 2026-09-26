"""K04: durable runs, краткий audit и вопросы без текста приватных сообщений."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("id", "house_id"),
        UniqueConstraint("house_id", "event_id"),
        Index("ix_agent_runs_house_case", "house_id", "case_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("houses.id"), nullable=False
    )
    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    case_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    case_version: Mapped[int | None] = mapped_column(Integer)
    pending_question_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_revision: Mapped[str | None] = mapped_column(String(200))
    prompt_revision: Mapped[str | None] = mapped_column(String(100))


class PendingQuestionRow(Base):
    __tablename__ = "pending_questions"
    __table_args__ = (
        Index(
            "uq_pending_questions_open_actor_case",
            "house_id",
            "case_id",
            "actor_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_pending_questions_expiry", "status", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("houses.id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("residents.id"), nullable=False
    )
    expected_case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_field: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    answered_event_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class AgentToolCallRow(Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "house_id"],
            ["agent_runs.id", "agent_runs.house_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", "sequence"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_version: Mapped[int | None] = mapped_column(Integer)
    source_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
