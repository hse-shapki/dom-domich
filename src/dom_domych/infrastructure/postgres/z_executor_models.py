"""Операции тестового исполнителя, отдельно от workflow дела."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class DemoExecutorRow(Base):
    __tablename__ = "demo_executor_operations"
    __table_args__ = (
        UniqueConstraint("house_id", "operation_key"),
        UniqueConstraint("house_id", "request_id"),
        ForeignKeyConstraint(["request_id", "house_id"], ["requests.id", "requests.house_id"]),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(250), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    registration_number: Mapped[str | None] = mapped_column(String(100))
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_event_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
