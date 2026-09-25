"""Core-таблицы A: дом, квартира, инженерные стояки и проживание."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class HouseRow(Base):
    __tablename__ = "houses"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    max_chat_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ApartmentRow(Base):
    __tablename__ = "apartments"
    __table_args__ = (
        UniqueConstraint("id", "house_id"),
        UniqueConstraint("house_id", "entrance", "number"),
        CheckConstraint("entrance > 0", name="entrance_positive"),
        CheckConstraint("floor >= 0", name="floor_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("houses.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    entrance: Mapped[int] = mapped_column(Integer, nullable=False)
    floor: Mapped[int] = mapped_column(Integer, nullable=False)


class RiserRow(Base):
    __tablename__ = "risers"
    __table_args__ = (
        UniqueConstraint("id", "house_id"),
        UniqueConstraint("house_id", "kind", "label"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("houses.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)


class ApartmentRiserRow(Base):
    __tablename__ = "apartment_risers"
    __table_args__ = (
        PrimaryKeyConstraint("house_id", "apartment_id", "riser_id"),
        ForeignKeyConstraint(
            ["apartment_id", "house_id"],
            ["apartments.id", "apartments.house_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["riser_id", "house_id"], ["risers.id", "risers.house_id"], ondelete="CASCADE"
        ),
    )

    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    apartment_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))
    riser_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True))


class ResidentRow(Base):
    __tablename__ = "residents"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    max_user_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dm_reachable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ResidencyRow(Base):
    __tablename__ = "residencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["apartment_id", "house_id"],
            ["apartments.id", "apartments.house_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("house_id", "apartment_id", "resident_id", "valid_from"),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="valid_interval"),
        Index("ix_residencies_house_status", "house_id", "confirmed", "adult"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    apartment_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    resident_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("residents.id", ondelete="CASCADE"), nullable=False
    )
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    adult: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(40), nullable=False)


class InboxEventRow(Base):
    __tablename__ = "inbox_events"
    __table_args__ = (
        UniqueConstraint("source", "source_key"),
        Index("ix_inbox_events_status_received", "status", "received_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(250), nullable=False)
    event_name: Mapped[str | None] = mapped_column(String(80))
    house_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    raw_update: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    normalized_event: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
