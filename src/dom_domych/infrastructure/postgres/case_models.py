"""Общее дело K: основа для поиска, сообщений и переходов состояния."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class CaseRow(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("id", "house_id"),
        Index("ix_cases_house_status_created", "house_id", "status", "created_at"),
        Index("ix_cases_house_location", "house_id", "entrance", "floor", "object_name"),
        ForeignKeyConstraint(["recurrence_of", "house_id"], ["cases.id", "cases.house_id"]),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    house_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("houses.id"), nullable=False, unique=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    entrance: Mapped[int | None] = mapped_column(Integer)
    floor: Mapped[int | None] = mapped_column(Integer)
    object_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recurrence_of: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    embedding: Mapped[list[float] | None] = mapped_column(JSONB)
    embedding_revision: Mapped[str | None] = mapped_column(String(200))
