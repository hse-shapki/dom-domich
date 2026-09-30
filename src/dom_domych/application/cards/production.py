"""Публикация обезличенных карточек через общий A outbox."""

from dataclasses import replace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.cards.builders import PublicCard, initiative_card, problem_card
from dom_domych.application.polls.callback import StoredPollAction
from dom_domych.contracts.max_ids import valid_max_chat_id
from dom_domych.domain.initiatives.models import InitiativeState
from dom_domych.domain.polls.models import PollKind, PollState, PollStatus, VoteChoice
from dom_domych.domain.ports.core import Clock, DeliveryIntent
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.initiatives import PostgresInitiativeRepository
from dom_domych.infrastructure.postgres.models import HouseRow, OutboxDeliveryRow
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.z_initiative_models import InitiativeRow
from dom_domych.infrastructure.postgres.z_poll_models import PollRow


class PostgresPublicCards:
    """Читает актуальную версию под lock и ставит карточку в outbox одной UoW."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def publish_initiative(self, case_id: UUID, house_id: UUID) -> UUID:
        async with self.sessions.begin() as session:
            initiative = await session.scalar(
                select(InitiativeRow)
                .where(InitiativeRow.case_id == case_id, InitiativeRow.house_id == house_id)
                .with_for_update()
            )
            if initiative is None:
                raise ValueError("initiative is missing or belongs to another house")
            state = await PostgresInitiativeRepository._load(session, case_id, house_id)
            await self._lock_poll(session, state.current.poll_id, house_id)
            poll = await PostgresPollRepository(session).get_state(state.current.poll_id, house_id)
            if poll is None:
                raise RuntimeError("current initiative poll is missing")
            return await self.enqueue_initiative(session, state, poll)

    async def enqueue_initiative(
        self, session: AsyncSession, state: InitiativeState, poll: PollState
    ) -> UUID:
        """Сохранить карточку инициативы в общей UoW вызывающего."""

        return await self._enqueue(session, initiative_card(state, poll), poll)

    async def publish_problem(self, poll_id: UUID, house_id: UUID) -> UUID:
        async with self.sessions.begin() as session:
            poll_row = await self._lock_poll(session, poll_id, house_id)
            case = await session.scalar(
                select(CaseRow).where(CaseRow.id == poll_row.case_id, CaseRow.house_id == house_id)
            )
            if case is None:
                raise ValueError("case is missing or belongs to another house")
            poll = await PostgresPollRepository(session).get_state(poll_id, house_id)
            if poll is None:
                raise RuntimeError("locked poll disappeared")
            return await self.enqueue_problem(session, case.title, case.version, poll)

    async def enqueue_problem(
        self, session: AsyncSession, title: str, case_version: int, poll: PollState
    ) -> UUID:
        """Сохранить карточку в UoW вызывающего вместе с открытием problem poll."""

        card = problem_card(title, poll)
        return await self._enqueue(
            session, replace(card, source_version=f"{case_version}:{poll.version}"), poll
        )

    @staticmethod
    async def _lock_poll(session: AsyncSession, poll_id: UUID, house_id: UUID) -> PollRow:
        row = await session.scalar(
            select(PollRow)
            .where(PollRow.id == poll_id, PollRow.house_id == house_id)
            .with_for_update()
        )
        if row is None:
            raise ValueError("poll is missing or belongs to another house")
        return row

    async def _enqueue(self, session: AsyncSession, card: PublicCard, poll: PollState) -> UUID:
        if len(card.text) > 4000:
            raise ValueError("public card exceeds MAX text limit")
        chat_id = await session.scalar(
            select(HouseRow.max_chat_id).where(HouseRow.id == card.house_id)
        )
        if chat_id is None or not valid_max_chat_id(chat_id):
            raise ValueError("house group chat is not configured")
        base = await session.scalar(
            select(OutboxDeliveryRow).where(
                OutboxDeliveryRow.house_id == card.house_id,
                OutboxDeliveryRow.operation_key == card.edit_key,
            )
        )
        if base is not None and base.text == card.text and base.chat_id == chat_id:
            if poll.status is not PollStatus.OPEN and not base.buttons:
                return base.id
            if poll.status is PollStatus.OPEN and len(base.buttons) == 2:
                first = await PostgresPollActionStore(session).get(base.buttons[0]["payload"])
                if (
                    first is not None
                    and first.poll_id == poll.definition.poll_id
                    and first.subject_revision == poll.definition.subject_revision
                    and not first.revoked
                ):
                    return base.id
        operation_key = (
            card.edit_key if base is None else f"{card.edit_key}:version:{card.source_version}"
        )
        existing = await session.scalar(
            select(OutboxDeliveryRow).where(
                OutboxDeliveryRow.house_id == card.house_id,
                OutboxDeliveryRow.operation_key == operation_key,
            )
        )
        if existing is not None:
            if existing.text != card.text or existing.chat_id != chat_id:
                raise ValueError("card operation key conflicts with current contents")
            return existing.id
        buttons = await self._buttons(session, poll, base)
        intent = DeliveryIntent(
            house_id=card.house_id,
            operation_key=operation_key,
            text=card.text,
            chat_id=chat_id,
            edit_key=card.edit_key if base is not None else None,
            buttons=buttons,
        )
        return await PostgresDeliveryQueue(session, self.clock).enqueue(intent)

    @staticmethod
    async def _buttons(
        session: AsyncSession, poll: PollState, base: OutboxDeliveryRow | None
    ) -> tuple[tuple[str, str], ...]:
        if poll.status is not PollStatus.OPEN:
            return ()
        actions = PostgresPollActionStore(session)
        if base is not None and len(base.buttons) == 2:
            prior = tuple((item["text"], item["payload"]) for item in base.buttons)
            first = await actions.get(prior[0][1])
            if (
                first is not None
                and first.poll_id == poll.definition.poll_id
                and first.subject_revision == poll.definition.subject_revision
                and not first.revoked
            ):
                return prior
        labels = (
            ("Подтверждаю", "Не подтверждаю")
            if poll.definition.kind is PollKind.PROBLEM_CONFIRMATION
            else ("За", "Против")
        )
        created: list[tuple[str, str]] = []
        for label, choice in zip(labels, (VoteChoice.YES, VoteChoice.NO), strict=True):
            token = await actions.create(
                StoredPollAction(
                    poll_id=poll.definition.poll_id,
                    house_id=poll.definition.house_id,
                    audience_id=poll.definition.audience_id,
                    subject_revision=poll.definition.subject_revision,
                    choice=choice,
                    expires_at=poll.definition.closes_at,
                )
            )
            created.append((label, token))
        return tuple(created)
