"""Публикация обезличенных карточек через общий A outbox."""

from dataclasses import replace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.cards.builders import PublicCard, initiative_card, problem_card
from dom_domych.domain.ports.core import Clock, DeliveryIntent
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.initiatives import PostgresInitiativeRepository
from dom_domych.infrastructure.postgres.models import HouseRow, OutboxDeliveryRow
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
            return await self._enqueue(session, initiative_card(state, poll))

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
            card = problem_card(case.title, poll)
            return await self._enqueue(
                session, replace(card, source_version=f"{case.version}:{poll.version}")
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

    async def _enqueue(self, session: AsyncSession, card: PublicCard) -> UUID:
        if len(card.text) > 4000:
            raise ValueError("public card exceeds MAX text limit")
        chat_id = await session.scalar(
            select(HouseRow.max_chat_id).where(HouseRow.id == card.house_id)
        )
        if chat_id is None or not chat_id.isdecimal():
            raise ValueError("house group chat is not configured")
        base = await session.scalar(
            select(OutboxDeliveryRow).where(
                OutboxDeliveryRow.house_id == card.house_id,
                OutboxDeliveryRow.operation_key == card.edit_key,
            )
        )
        intent = DeliveryIntent(
            house_id=card.house_id,
            operation_key=(
                card.edit_key if base is None else f"{card.edit_key}:version:{card.source_version}"
            ),
            text=card.text,
            chat_id=chat_id,
            edit_key=card.edit_key if base is not None else None,
        )
        return await PostgresDeliveryQueue(session, self.clock).enqueue(intent)
