"""Фиксация исходной аудитории аварии без ожидания коллективного порога."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.cases.production import case_audience_scope
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext


class _HouseContext:
    def __init__(self, house_id: UUID) -> None:
        self.house_id = house_id


def emergency_audience_key(case_id: UUID) -> str:
    return f"emergency:audience:{case_id}"


class EmergencyAudienceEventHandler:
    """Сохраняет frozen category, но не задерживает и не меняет request workflow."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def __call__(self, event: EventEnvelope) -> bool:
        if (
            event.name is not EventName.EMERGENCY_DETECTED
            or event.source is not EventSource.DOMAIN
            or event.house_id is None
            or event.entity is None
            or event.entity.case_id != event.entity.entity_id
        ):
            return False
        async with self.sessions.begin() as session:
            case = await session.scalar(
                select(CaseRow).where(
                    CaseRow.id == event.entity.entity_id,
                    CaseRow.house_id == event.house_id,
                )
            )
            if case is None or case.kind != "emergency":
                raise ValueError("emergency case is missing or belongs to another house")
            await AudienceService(
                PostgresHouseContext(session, self.clock),
                PostgresAudienceRepository(session),
                self.clock,
            ).resolve(
                case_audience_scope(case),
                _HouseContext(event.house_id),
                operation_key=emergency_audience_key(case.id),
            )
        return True
