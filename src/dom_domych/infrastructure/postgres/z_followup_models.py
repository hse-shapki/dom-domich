"""Напоминания и зафиксированная позиция инициативы Z08."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class InitiativeReminderBatchRow(Base):
    __tablename__ = "initiative_reminder_batches"
    __table_args__ = (
        UniqueConstraint("house_id", "operation_key"),
        ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    poll_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(250), nullable=False)
    targets: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InitiativeReminderRow(Base):
    __tablename__ = "initiative_reminders"
    __table_args__ = (
        UniqueConstraint("poll_id", "resident_id", "number"),
        ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        ForeignKeyConstraint(
            ["poll_id", "resident_id"], ["poll_members.poll_id", "poll_members.resident_id"]
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    poll_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    resident_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outbox_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("outbox_deliveries.id"), nullable=False
    )


class InitiativeDecisionRow(Base):
    __tablename__ = "initiative_decisions"
    __table_args__ = (
        UniqueConstraint("house_id", "operation_key"),
        ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        ForeignKeyConstraint(
            ["case_id", "initiative_revision"],
            ["initiative_revisions.case_id", "initiative_revisions.revision"],
        ),
    )

    poll_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    case_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    initiative_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    poll_version: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    policy_revision: Mapped[str] = mapped_column(String(100), nullable=False)
    demo: Mapped[bool] = mapped_column(Boolean, nullable=False)
    operation_key: Mapped[str] = mapped_column(String(250), nullable=False)
