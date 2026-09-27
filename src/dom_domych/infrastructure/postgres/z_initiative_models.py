"""Версии формулировки инициативы и ключи команд Z06."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class InitiativeRow(Base):
    __tablename__ = "initiatives"
    __table_args__ = (
        UniqueConstraint("case_id", "house_id"),
        ForeignKeyConstraint(["case_id", "house_id"], ["cases.id", "cases.house_id"]),
    )

    case_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    author_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("residents.id"), nullable=False
    )
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)


class InitiativeRevisionRow(Base):
    __tablename__ = "initiative_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "house_id"], ["initiatives.case_id", "initiatives.house_id"]
        ),
        ForeignKeyConstraint(["poll_id", "house_id"], ["polls.id", "polls.house_id"]),
        ForeignKeyConstraint(
            ["audience_id", "house_id"],
            ["audience_snapshots.id", "audience_snapshots.house_id"],
        ),
        UniqueConstraint("poll_id"),
    )

    case_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    wording: Mapped[str] = mapped_column(Text, nullable=False)
    audience_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    poll_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InitiativeOperationRow(Base):
    __tablename__ = "initiative_operations"
    __table_args__ = (
        UniqueConstraint("house_id", "operation_key"),
        ForeignKeyConstraint(
            ["case_id", "house_id"], ["initiatives.case_id", "initiatives.house_id"]
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(250), nullable=False)
    case_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
