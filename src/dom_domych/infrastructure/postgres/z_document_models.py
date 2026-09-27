"""Очередь PDF, неизменяемый snapshot и служебные метаданные файла."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("house_id", "operation_key"),
        Index("ix_documents_queue", "status", "lease_until", "created_at"),
        ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        ForeignKeyConstraint(
            ["audience_id", "house_id"],
            ["audience_snapshots.id", "audience_snapshots.house_id"],
        ),
        ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        ForeignKeyConstraint(["request_id", "house_id"], ["requests.id", "requests.house_id"]),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    case_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    audience_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    poll_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    request_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    recipient_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("residents.id"), nullable=False
    )
    operation_key: Mapped[str] = mapped_column(String(250), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    template_revision: Mapped[str] = mapped_column(String(100), nullable=False)
    snapshot_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_key: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    file_mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    file_retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
