"""Снимок проверки результата и её единственное итоговое решение."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class ResolutionCheckRow(Base):
    __tablename__ = "resolution_checks"
    __table_args__ = (
        UniqueConstraint("house_id", "start_operation_key"),
        UniqueConstraint("house_id", "done_event_id"),
        UniqueConstraint("house_id", "poll_id"),
        ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        ForeignKeyConstraint(["request_id", "house_id"], ["requests.id", "requests.house_id"]),
        ForeignKeyConstraint(
            ["original_audience_id", "house_id"],
            ["audience_snapshots.id", "audience_snapshots.house_id"],
        ),
        ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    case_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    original_audience_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    poll_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    case_version_at_start: Mapped[int] = mapped_column(Integer, nullable=False)
    done_event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    start_operation_key: Mapped[str] = mapped_column(String(250), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    poll_version_at_decision: Mapped[int | None] = mapped_column(Integer)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalize_operation_key: Mapped[str | None] = mapped_column(String(250))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
