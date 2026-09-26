"""K11: приватный outbox intent для срочного evidence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.contracts.base import ExecutionMode, TrustedContext
from dom_domych.domain.ports.core import Clock, DeliveryIntent
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue


class PostgresEmergencyEvidenceQueue:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def queue_private(
        self, case_id: UUID, context: TrustedContext, operation_key: str
    ) -> UUID:
        if context.actor_id is None:
            raise PermissionError("FORBIDDEN")
        prefix = "Демо. " if context.mode == ExecutionMode.DEMO else ""
        async with self.sessions.begin() as session:
            queue = PostgresDeliveryQueue(session, self.clock)
            return await queue.enqueue(
                DeliveryIntent(
                    house_id=context.house_id,
                    operation_key=operation_key,
                    text=(
                        f"{prefix}По срочному делу {case_id} можно прислать фото или уточнение "
                        "места в этот личный чат. Обращение готовится без ожидания фото."
                    ),
                    recipient_id=context.actor_id,
                )
            )
