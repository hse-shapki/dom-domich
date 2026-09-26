"""K07: поиск активных и недавно закрытых дел в границах дома и места."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.contracts import CaseCandidate, CaseKind, CaseSearch, CaseView
from dom_domych.infrastructure.postgres.case_models import CaseRow


def _candidate(row: CaseRow) -> CaseCandidate:
    return CaseCandidate(
        case_id=row.id,
        version=row.version,
        kind=CaseKind(row.kind),
        title=row.title,
        entrance=row.entrance,
        floor=row.floor,
        object_name=row.object_name,
        source_refs=(f"case:{row.id}",),
    )


class PostgresCaseReader:
    """Место/объект служат жёстким фильтром; score только упорядочивает факты."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_case(self, case_id: UUID, house_id: UUID) -> CaseView | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(CaseRow).where(CaseRow.id == case_id, CaseRow.house_id == house_id)
            )
            if row is None:
                return None
            return CaseView(
                case_id=row.id,
                version=row.version,
                kind=CaseKind(row.kind),
                title=row.title,
                status=row.status,
                source_refs=(f"case:{row.id}",),
            )

    async def search_candidates(
        self,
        command: CaseSearch,
        house_id: UUID,
        at: datetime,
        embedding: tuple[float, ...] | None,
        embedding_revision: str | None,
    ) -> tuple[CaseCandidate, ...]:
        searchable = func.to_tsvector("russian", CaseRow.title + " " + CaseRow.description)
        query = func.websearch_to_tsquery("russian", command.query)
        rank = func.ts_rank_cd(searchable, query)
        location_match = command.entrance is not None and command.object_name is not None
        filters = [
            CaseRow.house_id == house_id,
            or_(CaseRow.status != "closed", CaseRow.closed_at >= at - timedelta(days=30)),
        ]
        if command.entrance is not None:
            filters.append(CaseRow.entrance == command.entrance)
        if command.floor is not None:
            filters.append(CaseRow.floor == command.floor)
        if command.object_name is not None:
            filters.append(func.lower(CaseRow.object_name) == command.object_name.casefold())
        async with self.sessions() as session:
            statement = select(CaseRow).where(*filters)
            if not location_match:
                statement = statement.where(searchable.op("@@")(query))
            rows = (
                await session.scalars(
                    statement.order_by(rank.desc(), CaseRow.created_at.desc()).limit(10)
                )
            ).all()
            result = list(rows)
            if (
                embedding is not None
                and embedding_revision
                and await self._vector_available(session)
            ):
                vector_rows = await session.execute(
                    text(
                        "SELECT id FROM cases WHERE house_id = :house_id "
                        "AND (status <> 'closed' OR closed_at >= :recent) "
                        "AND (:entrance IS NULL OR entrance = :entrance) "
                        "AND (:floor IS NULL OR floor = :floor) "
                        "AND (:object_name IS NULL OR lower(object_name) = :object_name) "
                        "AND embedding_revision = :revision AND embedding_vector IS NOT NULL "
                        "AND embedding_vector <=> CAST(:vector AS vector) <= 0.35 "
                        "ORDER BY embedding_vector <=> CAST(:vector AS vector) LIMIT 10"
                    ),
                    {
                        "house_id": house_id,
                        "recent": at - timedelta(days=30),
                        "entrance": command.entrance,
                        "floor": command.floor,
                        "object_name": command.object_name.casefold()
                        if command.object_name is not None
                        else None,
                        "revision": embedding_revision,
                        "vector": self._vector_literal(embedding),
                    },
                )
                seen = {row.id for row in result}
                for (candidate_id,) in vector_rows:
                    if candidate_id in seen or len(result) >= 10:
                        continue
                    row = await session.get(CaseRow, candidate_id)
                    if row is not None and row.house_id == house_id:
                        result.append(row)
                        seen.add(row.id)
            return tuple(_candidate(row) for row in result)

    @staticmethod
    async def _vector_available(session: AsyncSession) -> bool:
        found = await session.scalar(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'cases' AND column_name = 'embedding_vector'"
            )
        )
        return found is not None

    @staticmethod
    def _vector_literal(vector: tuple[float, ...]) -> str:
        if len(vector) != 1024:
            raise ValueError("Неверная размерность embedding")
        return "[" + ",".join(str(value) for value in vector) + "]"
