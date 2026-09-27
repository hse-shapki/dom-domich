"""Неизменяемые снимки адресной аудитории Z03."""

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
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class AudienceSnapshotRow(Base):
    __tablename__ = "audience_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "house_id"),
        UniqueConstraint("house_id", "operation_key"),
        UniqueConstraint("supersedes_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("houses.id"), nullable=False
    )
    operation_key: Mapped[str] = mapped_column(String(250), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    entrance: Mapped[int | None] = mapped_column(Integer)
    floor: Mapped[int | None] = mapped_column(Integer)
    riser_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    riser_kind: Mapped[str | None] = mapped_column(String(40))
    criteria_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("audience_snapshots.id")
    )


class AudienceMemberRow(Base):
    __tablename__ = "audience_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["audience_id", "house_id"],
            ["audience_snapshots.id", "audience_snapshots.house_id"],
            ondelete="CASCADE",
        ),
    )

    audience_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    resident_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("residents.id"), primary_key=True
    )
    reachable_at_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)
