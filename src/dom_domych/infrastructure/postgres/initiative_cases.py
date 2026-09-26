"""K case adapter для проверки автора и версии инициативы Z06."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.infrastructure.postgres.case_models import CaseMessageRow, CaseRow


@dataclass(frozen=True, slots=True)
class InitiativeCaseReference:
    case_id: UUID
    house_id: UUID
    author_id: UUID
    kind: str
    version: int


class PostgresInitiativeCases:
    """Читает автора только из доверенной origin-связи дела в заданном доме."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_case(self, case_id: UUID, house_id: UUID) -> InitiativeCaseReference:
        async with self.sessions() as session:
            result = await session.execute(
                select(CaseRow, CaseMessageRow.actor_id)
                .join(
                    CaseMessageRow,
                    (CaseMessageRow.case_id == CaseRow.id)
                    & (CaseMessageRow.house_id == CaseRow.house_id)
                    & (CaseMessageRow.relation == "origin"),
                )
                .where(CaseRow.id == case_id, CaseRow.house_id == house_id)
                .limit(1)
            )
            row = result.one_or_none()
            if row is None:
                raise ValueError("CASE_NOT_FOUND")
            case, author_id = row
            if author_id is None:
                raise ValueError("CASE_NOT_FOUND")
            return InitiativeCaseReference(
                case_id=case.id,
                house_id=case.house_id,
                author_id=author_id,
                kind=case.kind,
                version=case.version,
            )
