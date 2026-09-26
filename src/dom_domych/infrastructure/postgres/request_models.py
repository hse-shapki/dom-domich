"""Черновик, регистрация и idempotency K10."""

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class RequestRow(Base):
    __tablename__ = "requests"
    __table_args__ = (
        UniqueConstraint("id", "house_id"),
        ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
        Index("ix_requests_house_case", "house_id", "case_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    case_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    responsible_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    rule_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("rule_versions.id"), nullable=False
    )
    source_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    approved_version: Mapped[int | None] = mapped_column(Integer)
    approval_actor: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("residents.id")
    )
    submit_operation_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    executor_operation_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    registration_id: Mapped[str | None] = mapped_column(String(100))
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_status: Mapped[str | None] = mapped_column(String(40))
    external_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    external_status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    document_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    document_file_key: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class RequestOperationRow(Base):
    __tablename__ = "request_operations"
    __table_args__ = (
        ForeignKeyConstraint(["request_id", "house_id"], ["requests.id", "requests.house_id"]),
    )

    house_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("houses.id"), primary_key=True
    )
    operation_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_view: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
