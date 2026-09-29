"""PDF для сохранённого K-черновика просроченного обращения."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.documents.cases import CaseDocumentPreparer, PositionWorkerContext
from dom_domych.application.requests.deadline import RequestDeadlineHandler
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.documents.snapshot import DocumentKind
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.case_models import CaseEventRow
from dom_domych.infrastructure.postgres.request_models import RequestRow


class RequestComplaintEventHandler:
    """Сначала K фиксирует review-only факты; Z делает PDF для согласовавшего жителя."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def __call__(self, event: EventEnvelope) -> bool:
        if (
            event.name is not EventName.REQUEST_DEADLINE_REACHED
            or event.source is not EventSource.SCHEDULER
            or event.house_id is None
            or event.entity is None
        ):
            return False
        await RequestDeadlineHandler(self.sessions, self.clock)(event)
        async with self.sessions() as session:
            request = await session.scalar(
                select(RequestRow).where(
                    RequestRow.id == event.entity.entity_id,
                    RequestRow.house_id == event.house_id,
                )
            )
            draft = await session.scalar(
                select(CaseEventRow.id).where(
                    CaseEventRow.house_id == event.house_id,
                    CaseEventRow.operation_id == event.event_id,
                    CaseEventRow.event_type == EventName.REQUEST_DEADLINE_REACHED.value,
                )
            )
            if request is None or request.approval_actor is None or draft is None:
                return False
        await CaseDocumentPreparer(self.sessions, self.clock).prepare(
            DocumentKind.COMPLAINT_DRAFT,
            request.case_id,
            PositionWorkerContext(event.house_id, request.approval_actor),
            operation_key=f"request:complaint:{request.id}:{draft}",
        )
        # K continuation продолжится после постановки PDF в очередь.
        return False
