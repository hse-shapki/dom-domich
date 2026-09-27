"""Production orchestration обычной проблемы через общий durable inbox."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.cards.production import PostgresPublicCards
from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.application.polls.service import PollService
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.polls.models import PollKind
from dom_domych.domain.polls.policy import demo_problem_policy
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseRow
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.z_poll_models import PollRow


class _HouseContext:
    def __init__(self, house_id: UUID) -> None:
        self.house_id = house_id


def _scope(case: CaseRow) -> AudienceScope:
    if case.floor is not None:
        if case.entrance is None:
            raise ValueError("floor scope requires a verified entrance")
        return AudienceScope(ScopeKind.FLOOR, entrance=case.entrance, floor=case.floor)
    if case.entrance is not None:
        return AudienceScope(ScopeKind.ENTRANCE, entrance=case.entrance)
    return AudienceScope(ScopeKind.HOUSE)


class PostgresProblemEventHandler:
    """Открывает frozen audience/poll и карточку в одной короткой SQL-транзакции."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def __call__(self, event: EventEnvelope) -> bool:
        if (
            event.name is not EventName.PROBLEM_DETECTED
            or event.source is not EventSource.DOMAIN
            or event.house_id is None
            or event.entity is None
            or event.entity.case_id != event.entity.entity_id
        ):
            return False
        async with self.sessions.begin() as session:
            case = await session.scalar(
                select(CaseRow)
                .where(
                    CaseRow.id == event.entity.entity_id,
                    CaseRow.house_id == event.house_id,
                )
                .with_for_update()
            )
            if case is None or case.kind != "problem":
                raise ValueError("problem case is missing or belongs to another house")
            if case.status != "detected":
                existing = await session.scalar(
                    select(PollRow.id).where(
                        PollRow.case_id == case.id,
                        PollRow.house_id == event.house_id,
                        PollRow.kind == PollKind.PROBLEM_CONFIRMATION.value,
                    )
                )
                if case.status == "collecting" and existing is None:
                    raise RuntimeError("collecting problem has no poll")
                return True
            if case.version != event.entity.entity_version:
                raise ValueError("problem event version is stale")
            context = _HouseContext(event.house_id)
            audience = await AudienceService(
                PostgresHouseContext(session, self.clock),
                PostgresAudienceRepository(session),
                self.clock,
            ).resolve(
                _scope(case),
                context,
                operation_key=f"problem:audience:{case.id}:{case.version}",
            )
            previous_version = case.version
            case.version += 1
            if audience.eligible_count == 0:
                case.status = "needs_evidence"
                self._case_event(session, case, previous_version, event, audience.audience_id, None)
                return True
            poll = await PollService(PostgresPollRepository(session), self.clock).open(
                case.id,
                audience,
                PollKind.PROBLEM_CONFIRMATION,
                demo_problem_policy(),
                previous_version,
                context,
                operation_key=f"problem:poll:{case.id}:{previous_version}",
            )
            case.status = "collecting"
            self._case_event(
                session,
                case,
                previous_version,
                event,
                audience.audience_id,
                poll.definition.poll_id,
            )
            await PostgresPublicCards(self.sessions, self.clock).enqueue_problem(
                session, case.title, case.version, poll
            )
        return True

    def _case_event(
        self,
        session: AsyncSession,
        case: CaseRow,
        previous_version: int,
        source: EventEnvelope,
        audience_id: UUID,
        poll_id: UUID | None,
    ) -> None:
        session.add(
            CaseEventRow(
                id=uuid4(),
                case_id=case.id,
                house_id=case.house_id,
                event_type="problem.collecting" if poll_id is not None else "problem.no_audience",
                before_version=previous_version,
                after_version=case.version,
                actor_id=None,
                source_message_id=None,
                operation_id=source.event_id,
                occurred_at=self.clock.now(),
                facts={
                    "audience_id": str(audience_id),
                    "poll_id": str(poll_id) if poll_id is not None else None,
                },
            )
        )


def register_problem_events(
    dispatcher: EventDispatcher,
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
) -> None:
    dispatcher.register(EventName.PROBLEM_DETECTED, PostgresProblemEventHandler(sessions, clock))
