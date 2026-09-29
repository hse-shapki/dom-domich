"""Источник аудитории исполнения: исходная проблема или принятая редакция инициативы."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.application.requests.emergency_runtime import emergency_audience_key
from dom_domych.domain.polls.models import PollKind
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.z_audience_models import AudienceSnapshotRow
from dom_domych.infrastructure.postgres.z_initiative_models import (
    InitiativeRevisionRow,
    InitiativeRow,
)
from dom_domych.infrastructure.postgres.z_poll_models import PollRow


async def original_poll(session: AsyncSession, case: CaseRow) -> PollRow | None:
    """Исключает отменённые редакции инициативы и последующие опросы результата."""
    query = select(PollRow).where(PollRow.case_id == case.id, PollRow.house_id == case.house_id)
    if case.kind == "initiative":
        query = query.join(
            InitiativeRevisionRow,
            (InitiativeRevisionRow.poll_id == PollRow.id)
            & (InitiativeRevisionRow.house_id == case.house_id),
        ).join(
            InitiativeRow,
            (InitiativeRow.case_id == InitiativeRevisionRow.case_id)
            & (InitiativeRow.house_id == case.house_id)
            & (InitiativeRow.current_revision == InitiativeRevisionRow.revision),
        )
        query = query.where(PollRow.kind == PollKind.INITIATIVE_POSITION.value)
    elif case.kind == "problem":
        query = query.where(PollRow.kind == PollKind.PROBLEM_CONFIRMATION.value)
    else:
        return None
    return await session.scalar(query.order_by(PollRow.opens_at, PollRow.id).limit(1))


async def original_audience_id(session: AsyncSession, case: CaseRow) -> UUID | None:
    """Для аварии возвращает frozen snapshot, созданный до обращения без poll."""
    poll = await original_poll(session, case)
    if poll is not None:
        return poll.audience_id
    if case.kind == "emergency":
        return await session.scalar(
            select(AudienceSnapshotRow.id).where(
                AudienceSnapshotRow.house_id == case.house_id,
                AudienceSnapshotRow.operation_key == emergency_audience_key(case.id),
            )
        )
    return None
