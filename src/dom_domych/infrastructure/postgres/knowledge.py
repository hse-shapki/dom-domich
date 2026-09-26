"""Tenant-scoped хранение проверенных знаний с русским полнотекстовым поиском."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from dom_domych.agent.contracts import KnowledgeHit
from dom_domych.domain.knowledge.models import RuleVersion, SourceRevision
from dom_domych.infrastructure.postgres.knowledge_models import (
    KnowledgeChunkRow,
    KnowledgeSourceRow,
    RuleVersionRow,
)


def _valid_at(
    column_from: InstrumentedAttribute[datetime | None],
    column_until: InstrumentedAttribute[datetime | None],
    at: datetime,
) -> ColumnElement[bool]:
    return or_(column_from.is_(None), column_from <= at) & or_(
        column_until.is_(None), column_until > at
    )


class PostgresKnowledgeRepository:
    """Все чтения ограничены доверенным house_id и проверенной ревизией."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def add_source(
        self,
        source: SourceRevision,
        chunks: tuple[str, ...],
        embeddings: tuple[tuple[float, ...], ...] | None,
        embedding_revision: str | None,
    ) -> None:
        if embeddings is not None and len(embeddings) != len(chunks):
            raise ValueError("Несовпадение числа chunks и embeddings")
        async with self.sessions.begin() as session:
            latest = await session.scalar(
                select(func.max(KnowledgeSourceRow.revision)).where(
                    KnowledgeSourceRow.source_id == source.source_id
                )
            )
            if latest is not None and source.revision <= latest:
                raise ValueError("SOURCE_REVISION_NOT_NEW")
            session.add(
                KnowledgeSourceRow(
                    source_id=source.source_id,
                    revision=source.revision,
                    house_id=source.house_id,
                    title=source.title,
                    uri=source.uri,
                    text=source.text,
                    reviewed=False,
                    valid_from=source.valid_from,
                    valid_until=source.valid_until,
                )
            )
            await session.flush()
            for ordinal, chunk in enumerate(chunks):
                session.add(
                    KnowledgeChunkRow(
                        id=uuid4(),
                        source_id=source.source_id,
                        revision=source.revision,
                        ordinal=ordinal,
                        text=chunk,
                        embedding=list(embeddings[ordinal]) if embeddings is not None else None,
                        embedding_revision=embedding_revision,
                    )
                )
            if embeddings is not None and await self._vector_available(session):
                await session.flush()
                rows = (
                    await session.scalars(
                        select(KnowledgeChunkRow).where(
                            KnowledgeChunkRow.source_id == source.source_id,
                            KnowledgeChunkRow.revision == source.revision,
                        )
                    )
                ).all()
                for row in rows:
                    vector = embeddings[row.ordinal]
                    await session.execute(
                        text(
                            "UPDATE knowledge_chunks "
                            "SET embedding_vector = CAST(:vector AS vector) WHERE id = :chunk_id"
                        ),
                        {"vector": self._vector_literal(vector), "chunk_id": row.id},
                    )

    async def review_source(self, source_id: UUID, revision: int, house_id: UUID | None) -> bool:
        async with self.sessions.begin() as session:
            reviewed_id = await session.scalar(
                update(KnowledgeSourceRow)
                .where(
                    KnowledgeSourceRow.source_id == source_id,
                    KnowledgeSourceRow.revision == revision,
                    KnowledgeSourceRow.house_id.is_(None)
                    if house_id is None
                    else KnowledgeSourceRow.house_id == house_id,
                )
                .values(reviewed=True)
                .returning(KnowledgeSourceRow.source_id)
            )
            return reviewed_id is not None

    async def add_rule(self, rule: RuleVersion) -> None:
        async with self.sessions.begin() as session:
            source = await session.get(
                KnowledgeSourceRow, (rule.source_id, rule.source_revision), with_for_update=True
            )
            if source is None or not source.reviewed or source.house_id != rule.house_id:
                raise ValueError("RULE_SOURCE_NOT_REVIEWED_OR_SCOPE_MISMATCH")
            session.add(
                RuleVersionRow(
                    id=rule.rule_id,
                    source_id=rule.source_id,
                    source_revision=rule.source_revision,
                    house_id=rule.house_id,
                    topic=rule.topic,
                    responsible_id=rule.responsible_id,
                    duration_seconds=int(rule.deadline.total_seconds()) if rule.deadline else None,
                    deadline_origin=rule.deadline_origin,
                    valid_from=rule.valid_from,
                    valid_until=rule.valid_until,
                )
            )

    async def search(
        self,
        query: str,
        topic: str | None,
        house_id: UUID,
        at: datetime,
        limit: int,
        embedding: tuple[float, ...] | None,
        embedding_revision: str | None,
    ) -> tuple[KnowledgeHit, ...]:
        vector = func.to_tsvector("russian", KnowledgeChunkRow.text)
        tsquery = func.websearch_to_tsquery("russian", query)
        rank = func.ts_rank_cd(vector, tsquery)
        async with self.sessions() as session:
            statement = (
                select(KnowledgeChunkRow, KnowledgeSourceRow)
                .join(
                    KnowledgeSourceRow,
                    (KnowledgeChunkRow.source_id == KnowledgeSourceRow.source_id)
                    & (KnowledgeChunkRow.revision == KnowledgeSourceRow.revision),
                )
                .where(
                    vector.op("@@")(tsquery),
                    KnowledgeSourceRow.reviewed.is_(True),
                    or_(
                        KnowledgeSourceRow.house_id.is_(None),
                        KnowledgeSourceRow.house_id == house_id,
                    ),
                    _valid_at(KnowledgeSourceRow.valid_from, KnowledgeSourceRow.valid_until, at),
                )
                .order_by(rank.desc(), KnowledgeChunkRow.ordinal)
                .limit(limit)
            )
            rows = (await session.execute(statement)).all()
            hits = [
                KnowledgeHit(
                    source_id=source.source_id,
                    revision=source.revision,
                    excerpt=chunk.text,
                    reviewed=True,
                )
                for chunk, source in rows
            ]
            if (
                embedding is not None
                and embedding_revision
                and await self._vector_available(session)
            ):
                vector_rows = await session.execute(
                    text(
                        "SELECT s.source_id, s.revision, c.text "
                        "FROM knowledge_chunks c JOIN knowledge_sources s "
                        "ON s.source_id = c.source_id AND s.revision = c.revision "
                        "WHERE s.reviewed AND (s.house_id IS NULL OR s.house_id = :house_id) "
                        "AND (s.valid_from IS NULL OR s.valid_from <= :at) "
                        "AND (s.valid_until IS NULL OR s.valid_until > :at) "
                        "AND c.embedding_revision = :revision AND c.embedding_vector IS NOT NULL "
                        "AND c.embedding_vector <=> CAST(:vector AS vector) <= 0.35 "
                        "ORDER BY c.embedding_vector <=> CAST(:vector AS vector) LIMIT :limit"
                    ),
                    {
                        "house_id": house_id,
                        "at": at,
                        "revision": embedding_revision,
                        "vector": self._vector_literal(embedding),
                        "limit": limit,
                    },
                )
                seen = {(hit.source_id, hit.revision, hit.excerpt) for hit in hits}
                for source_id, revision, excerpt in vector_rows:
                    if (source_id, revision, excerpt) not in seen and len(hits) < limit:
                        hits.append(
                            KnowledgeHit(
                                source_id=cast(UUID, source_id),
                                revision=cast(int, revision),
                                excerpt=cast(str, excerpt),
                                reviewed=True,
                            )
                        )
            return tuple(hits)

    @staticmethod
    async def _vector_available(session: AsyncSession) -> bool:
        found = await session.scalar(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding_vector'"
            )
        )
        return found is not None

    @staticmethod
    def _vector_literal(vector: tuple[float, ...]) -> str:
        if len(vector) != 1024:
            raise ValueError("Неверная размерность embedding")
        return "[" + ",".join(str(value) for value in vector) + "]"

    async def find_rule(self, topic: str, house_id: UUID, at: datetime) -> RuleVersion | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(RuleVersionRow)
                .join(
                    KnowledgeSourceRow,
                    (RuleVersionRow.source_id == KnowledgeSourceRow.source_id)
                    & (RuleVersionRow.source_revision == KnowledgeSourceRow.revision),
                )
                .where(
                    RuleVersionRow.topic == topic,
                    KnowledgeSourceRow.reviewed.is_(True),
                    or_(RuleVersionRow.house_id.is_(None), RuleVersionRow.house_id == house_id),
                    _valid_at(RuleVersionRow.valid_from, RuleVersionRow.valid_until, at),
                    _valid_at(KnowledgeSourceRow.valid_from, KnowledgeSourceRow.valid_until, at),
                )
                .order_by(RuleVersionRow.source_revision.desc())
                .limit(1)
            )
            if row is None:
                return None
            return RuleVersion(
                rule_id=row.id,
                source_id=row.source_id,
                source_revision=row.source_revision,
                house_id=row.house_id,
                topic=row.topic,
                responsible_id=row.responsible_id,
                deadline=timedelta(seconds=row.duration_seconds)
                if row.duration_seconds is not None
                else None,
                deadline_origin=row.deadline_origin,
                valid_from=row.valid_from,
                valid_until=row.valid_until,
            )
