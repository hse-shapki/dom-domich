"""Снимки правил, состав, текущие ответы и история опроса Z04."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class PollRow(Base):
    __tablename__ = "polls"
    __table_args__ = (
        UniqueConstraint("id", "house_id"),
        UniqueConstraint("id", "audience_id"),
        UniqueConstraint("house_id", "operation_key"),
        UniqueConstraint("case_id", "audience_id", "kind", "subject_revision"),
        ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        ForeignKeyConstraint(
            ["audience_id", "house_id"],
            ["audience_snapshots.id", "audience_snapshots.house_id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    case_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    audience_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(250), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    policy: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    subject_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(40))
    threshold_emitted: Mapped[bool] = mapped_column(Boolean, nullable=False)


class PollMemberRow(Base):
    __tablename__ = "poll_members"
    __table_args__ = (
        ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        ForeignKeyConstraint(["poll_id", "audience_id"], ["polls.id", "polls.audience_id"]),
        ForeignKeyConstraint(
            ["audience_id", "resident_id"],
            ["audience_members.audience_id", "audience_members.resident_id"],
        ),
    )

    poll_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    audience_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    resident_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)


class PollAnswerRow(Base):
    __tablename__ = "poll_answers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["poll_id", "resident_id"],
            ["poll_members.poll_id", "poll_members.resident_id"],
        ),
    )

    poll_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    resident_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    choice: Mapped[str] = mapped_column(String(10), nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class PollAnswerHistoryRow(Base):
    __tablename__ = "poll_answer_history"
    __table_args__ = (
        UniqueConstraint("source_event_id"),
        UniqueConstraint("poll_id", "resident_id", "revision"),
        ForeignKeyConstraint(
            ["poll_id", "resident_id"],
            ["poll_members.poll_id", "poll_members.resident_id"],
        ),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    poll_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    resident_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    choice: Mapped[str] = mapped_column(String(10), nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
