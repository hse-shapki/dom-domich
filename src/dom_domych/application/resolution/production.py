"""Доверенные события исполнителя и poll связывают проверку результата с runtime."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.initiatives.followup import InitiativeFollowupService
from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.application.jobs.scheduler import RevisionRouter
from dom_domych.application.resolution.service import ResolutionService
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.polls.models import PollKind
from dom_domych.domain.polls.policy import demo_resolution_policy
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.demo_executor import PostgresDemoExecutor
from dom_domych.infrastructure.postgres.initiative_followup import (
    PostgresCurrentDeliveryRights,
    PostgresInitiativeFollowupRepository,
)
from dom_domych.infrastructure.postgres.initiatives import PostgresInitiativeRepository
from dom_domych.infrastructure.postgres.polls import (
    PostgresPollRepository,
    PostgresPollRevisionReader,
)
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.requests import PostgresRequestStore
from dom_domych.infrastructure.postgres.resolution import (
    PostgresResolutionCasePort,
    PostgresResolutionStore,
)
from dom_domych.infrastructure.postgres.z_resolution_models import ResolutionCheckRow


class _ResolutionWorkerContext:
    def __init__(self, house_id: UUID) -> None:
        self.house_id = house_id
        self.capabilities = frozenset({"resolution.start_from_executor", "resolution.finalize"})


class PostgresResolutionEventHandler:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def handle_registration(self, event: EventEnvelope) -> bool:
        if (
            event.name is not EventName.REQUEST_REGISTERED
            or event.source is not EventSource.EXECUTOR
            or event.house_id is None
            or event.entity is None
        ):
            return False
        operation = await PostgresDemoExecutor(self.sessions, self.clock).get(
            event.house_id, event.entity.entity_id
        )
        await PostgresRequestStore(self.sessions, self.clock).register(
            event.entity.entity_id, event.house_id, operation
        )
        # K store выпустил отдельное DOMAIN событие для agent continuation.
        return True

    async def handle_status(self, event: EventEnvelope) -> bool:
        """Вызывается после K RequestEventHandler, который уже применил external version."""

        if (
            event.name is not EventName.REQUEST_STATUS_CHANGED
            or event.source is not EventSource.EXECUTOR
            or event.house_id is None
            or event.entity is None
            or event.entity.case_id is None
        ):
            return False
        async with self.sessions() as session:
            request = await session.scalar(
                select(RequestRow).where(
                    RequestRow.id == event.entity.entity_id,
                    RequestRow.house_id == event.house_id,
                )
            )
            if request is None or request.external_status != "done":
                return False
        operation = await PostgresDemoExecutor(self.sessions, self.clock).get(
            event.house_id, event.entity.entity_id
        )
        if event.event_id not in operation.processed_event_ids:
            return False
        cases = PostgresResolutionCasePort(self.sessions)
        case = await cases.get_for_resolution(event.entity.case_id, event.house_id)
        async with self.sessions() as session:
            audience = await PostgresAudienceRepository(session).get_scoped(
                case.original_audience_id, event.house_id
            )
        if audience is None:
            raise ValueError("original resolution audience disappeared")
        await ResolutionService(
            cases, PostgresResolutionStore(self.sessions, self.clock), self.clock
        ).start_check(
            case.case_id,
            operation,
            event.event_id,
            audience,
            demo_resolution_policy(),
            timedelta(hours=2),
            _ResolutionWorkerContext(event.house_id),
            operation_key=f"resolution:start:{event.event_id}",
        )
        return False

    async def handle_poll_expired(self, event: EventEnvelope) -> bool:
        if event.house_id is None or event.entity is None:
            raise ValueError("poll event needs house and entity")
        poll_id = event.entity.entity_id
        if event.source is EventSource.SCHEDULER:
            async with self.sessions.begin() as session:
                await PostgresPollRepository(session).finalize_atomic(
                    poll_id, event.house_id, self.clock.now()
                )
            # PollRepository записал DOMAIN event; он придёт после commit.
            return True
        if event.source is not EventSource.DOMAIN:
            return False
        async with self.sessions() as session:
            poll = await PostgresPollRepository(session).get_state(poll_id, event.house_id)
            check = await session.scalar(
                select(ResolutionCheckRow).where(
                    ResolutionCheckRow.poll_id == poll_id,
                    ResolutionCheckRow.house_id == event.house_id,
                )
            )
        if poll is None:
            return False
        if poll.definition.kind is PollKind.INITIATIVE_POSITION:
            state = await PostgresInitiativeRepository(self.sessions).get(
                poll.definition.case_id, event.house_id
            )
            await InitiativeFollowupService(
                PostgresInitiativeFollowupRepository(self.sessions, self.clock),
                PostgresCurrentDeliveryRights(self.sessions, self.clock),
                self.clock,
            ).finalize_position(
                state,
                poll,
                operation_key=f"initiative:decision:{poll.definition.poll_id}",
            )
            return False
        if poll.definition.kind is not PollKind.RESOLUTION_CHECK or check is None:
            return False
        await ResolutionService(
            PostgresResolutionCasePort(self.sessions),
            PostgresResolutionStore(self.sessions, self.clock),
            self.clock,
        ).finalize(
            check.id,
            poll,
            _ResolutionWorkerContext(event.house_id),
            operation_key=f"resolution:final:{check.id}",
        )
        return False


def register_z_poll_events(
    dispatcher: EventDispatcher,
    revisions: RevisionRouter,
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
) -> PostgresResolutionEventHandler:
    handler = PostgresResolutionEventHandler(sessions, clock)
    dispatcher.register(EventName.REQUEST_REGISTERED, handler.handle_registration)
    dispatcher.register(EventName.POLL_EXPIRED, handler.handle_poll_expired)
    revisions.register(EventName.POLL_EXPIRED, PostgresPollRevisionReader(sessions))
    return handler
