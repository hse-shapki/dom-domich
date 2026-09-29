"""Production orchestration инициативы через общий durable inbox."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.cards.production import PostgresPublicCards
from dom_domych.application.cases.production import case_audience_scope
from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.initiatives.models import InitiativeRevision, InitiativeState
from dom_domych.domain.polls.models import PollDefinition, PollKind, PollState
from dom_domych.domain.polls.policy import demo_initiative_policy
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseMessageRow, CaseRow
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.initiatives import PostgresInitiativeRepository
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.z_initiative_models import InitiativeRow

_DEMO_WINDOW = timedelta(days=2)


class _InitiativeContext:
    def __init__(self, house_id: UUID, actor_id: UUID) -> None:
        self.house_id = house_id
        self.actor_id = actor_id


class PostgresInitiativeEventHandler:
    """Сохраняет audience/initiative/poll/reminders/card в одной SQL-транзакции."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def __call__(self, event: EventEnvelope) -> bool:
        if (
            event.name is not EventName.INITIATIVE_DETECTED
            or event.source is not EventSource.DOMAIN
            or event.house_id is None
            or event.entity is None
            or event.entity.case_id != event.entity.entity_id
        ):
            return False
        async with self.sessions.begin() as session:
            case = await session.scalar(
                select(CaseRow)
                .where(CaseRow.id == event.entity.entity_id, CaseRow.house_id == event.house_id)
                .with_for_update()
            )
            if case is None or case.kind != "initiative":
                raise ValueError("initiative case is missing or belongs to another house")
            if case.status != "detected":
                existing = await session.scalar(
                    select(InitiativeRow.case_id).where(
                        InitiativeRow.case_id == case.id,
                        InitiativeRow.house_id == event.house_id,
                    )
                )
                if case.status == "collecting":
                    if existing is None:
                        raise RuntimeError("collecting initiative has no state")
                    state = await PostgresInitiativeRepository._load(
                        session, case.id, case.house_id
                    )
                    poll = await PostgresPollRepository(session).get_state(
                        state.current.poll_id, case.house_id
                    )
                    if poll is None:
                        raise RuntimeError("current initiative poll is missing")
                    await PostgresPublicCards(self.sessions, self.clock).enqueue_initiative(
                        session, state, poll
                    )
                return True
            if case.version != event.entity.entity_version:
                raise ValueError("initiative event version is stale")
            author_id = await session.scalar(
                select(CaseMessageRow.actor_id)
                .where(
                    CaseMessageRow.case_id == case.id,
                    CaseMessageRow.house_id == event.house_id,
                    CaseMessageRow.relation == "origin",
                )
                .limit(1)
            )
            if author_id is None:
                raise ValueError("initiative author is missing")
            context = _InitiativeContext(event.house_id, author_id)
            audience = await AudienceService(
                PostgresHouseContext(session, self.clock),
                PostgresAudienceRepository(session),
                self.clock,
            ).resolve(
                case_audience_scope(case),
                context,
                operation_key=f"initiative:audience:{case.id}:{case.version}",
            )
            previous_version = case.version
            case.version += 1
            if audience.eligible_count == 0:
                case.status = "not_supported"
                self._case_event(session, case, previous_version, event, audience.audience_id, None)
                return True
            case.status = "collecting"
            now = self.clock.now()
            revision = InitiativeRevision(
                1, case.description.strip(), audience.audience_id, uuid4(), now
            )
            state = InitiativeState(case.id, case.house_id, author_id, case.version, (revision,))
            policy = demo_initiative_policy()
            poll = PollState(
                PollDefinition(
                    poll_id=revision.poll_id,
                    case_id=case.id,
                    house_id=case.house_id,
                    audience_id=audience.audience_id,
                    kind=PollKind.INITIATIVE_POSITION,
                    policy=policy,
                    subject_revision=revision.revision,
                    eligible_residents=frozenset(item.resident_id for item in audience.members),
                    opens_at=now,
                    closes_at=now + _DEMO_WINDOW,
                )
            )
            repository = PostgresInitiativeRepository(self.sessions)
            await repository.create_and_open_in_session(
                session,
                state,
                poll,
                tuple(item.resident_id for item in audience.members),
                f"initiative:create:{case.id}:{previous_version}",
            )
            self._case_event(
                session, case, previous_version, event, audience.audience_id, revision.poll_id
            )
            await PostgresPublicCards(self.sessions, self.clock).enqueue_initiative(
                session, state, poll
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
                event_type=(
                    "initiative.collecting" if poll_id is not None else "initiative.no_audience"
                ),
                before_version=previous_version,
                after_version=case.version,
                actor_id=None,
                source_message_id=None,
                operation_id=source.event_id,
                occurred_at=self.clock.now(),
                facts={
                    "audience_id": str(audience_id),
                    "poll_id": str(poll_id) if poll_id is not None else None,
                    "window_seconds": int(_DEMO_WINDOW.total_seconds()),
                    "demo": True,
                },
            )
        )


def register_initiative_events(
    dispatcher: EventDispatcher,
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
) -> None:
    dispatcher.register(
        EventName.INITIATIVE_DETECTED, PostgresInitiativeEventHandler(sessions, clock)
    )
