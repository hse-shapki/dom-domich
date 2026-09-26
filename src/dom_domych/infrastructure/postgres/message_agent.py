"""PostgreSQL adapters доверенного MAX actor/house и ответа agent в outbox."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.agent.messages import MessagePrincipal
from dom_domych.contracts.base import ExecutionMode
from dom_domych.contracts.events import EventEnvelope
from dom_domych.domain.ports.core import Clock, DeliveryIntent
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.models import HouseRow, ResidencyRow, ResidentRow


class PostgresMessagePrincipals:
    """Даёт capabilities только активному подтверждённому жителю выбранного дома."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        resident_capabilities: frozenset[str],
    ) -> None:
        self.sessions = sessions
        self.clock = clock
        self.resident_capabilities = resident_capabilities

    async def resolve(self, event: EventEnvelope) -> MessagePrincipal | None:
        if event.message is None:
            return None
        async with self.sessions() as session:
            resident = await session.scalar(
                select(ResidentRow).where(ResidentRow.max_user_id == event.message.sender_user_id)
            )
            if resident is None:
                return None
            house = await self._house(session, event.message.chat_id, resident)
            if house is None:
                return None
            now = self.clock.now()
            residency = await session.scalar(
                select(ResidencyRow.id).where(
                    ResidencyRow.house_id == house.id,
                    ResidencyRow.resident_id == resident.id,
                    ResidencyRow.confirmed.is_(True),
                    ResidencyRow.valid_from <= now,
                    or_(ResidencyRow.valid_until.is_(None), ResidencyRow.valid_until > now),
                )
            )
            if residency is None:
                return None
            return MessagePrincipal(
                house_id=house.id,
                actor_id=resident.id,
                mode=ExecutionMode.DEMO if house.demo else ExecutionMode.LIVE,
                capabilities=self.resident_capabilities,
            )

    @staticmethod
    async def _house(session: AsyncSession, chat_id: str, resident: ResidentRow) -> HouseRow | None:
        if chat_id.startswith("dm:"):
            return (
                await session.get(HouseRow, resident.active_house_id)
                if resident.active_house_id is not None
                else None
            )
        return await session.scalar(select(HouseRow).where(HouseRow.max_chat_id == chat_id))


class PostgresMessageReplies:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def enqueue(self, event: EventEnvelope, principal: MessagePrincipal, text: str) -> UUID:
        if event.message is None:
            raise ValueError("MESSAGE_REQUIRED")
        direct = event.message.chat_id.startswith("dm:")
        intent = DeliveryIntent(
            house_id=principal.house_id,
            operation_key=f"agent-reply:{event.event_id}",
            text=text,
            recipient_id=principal.actor_id if direct else None,
            chat_id=None if direct else event.message.chat_id,
        )
        async with self.sessions.begin() as session:
            return await PostgresDeliveryQueue(session, self.clock).enqueue(intent)
