"""Версии источников, фрагменты и проверенные правила K05."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from dom_domych.infrastructure.postgres.base import Base


class KnowledgeSourceRow(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (Index("ix_knowledge_sources_scope", "house_id", "reviewed"),)

    source_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    house_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("houses.id"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed: Mapped[bool] = mapped_column(nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeChunkRow(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "revision"],
            ["knowledge_sources.source_id", "knowledge_sources.revision"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSONB)
    embedding_revision: Mapped[str | None] = mapped_column(String(200))


class RuleVersionRow(Base):
    __tablename__ = "rule_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "source_revision"],
            ["knowledge_sources.source_id", "knowledge_sources.revision"],
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    house_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("houses.id"))
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    responsible_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    deadline_origin: Mapped[str | None] = mapped_column(String(100))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
