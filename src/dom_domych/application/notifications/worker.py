"""Отправка намерений outbox после commit бизнес-транзакции."""

from datetime import timedelta

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.max.client import MaxApiClient, MaxApiError
from dom_domych.infrastructure.postgres.delivery import PendingDelivery, PostgresDeliveryQueue

logger = structlog.get_logger()


class DeliveryWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        max_client: MaxApiClient,
        clock: Clock,
        worker_id: str,
        max_attempts: int = 5,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.sessions = sessions
        self.max_client = max_client
        self.clock = clock
        self.worker_id = worker_id
        self.max_attempts = max_attempts

    async def run_once(self) -> bool:
        async with self.sessions.begin() as session:
            delivery = await PostgresDeliveryQueue(session, self.clock).claim(
                self.worker_id, self.clock.now(), timedelta(seconds=60)
            )
        if delivery is None:
            return False
        await self._deliver(delivery)
        return True

    async def _deliver(self, delivery: PendingDelivery) -> None:
        if delivery.file_key is not None:
            await self._settle(
                delivery, "waiting_attachment", error_code="attachment_transport_missing"
            )
            return
        async with self.sessions() as session:
            queue = PostgresDeliveryQueue(session, self.clock)
            user_id = await queue.resolve_target(delivery, self.clock.now())
            edit_message_id = await queue.edit_message_id(delivery)
        if delivery.recipient_id is not None and user_id is None:
            await self._settle(delivery, "unreachable", error_code="recipient_unavailable")
            return
        if delivery.edit_key is not None and edit_message_id is None:
            await self._retry(delivery, "edit_target_pending")
            return
        try:
            if edit_message_id is not None:
                await self.max_client.edit_text(edit_message_id, delivery.text)
                message_id = edit_message_id
            elif user_id is not None:
                message_id = await self.max_client.send_text(delivery.text, user_id=user_id)
            else:
                assert delivery.chat_id is not None
                if not delivery.chat_id.isdecimal():
                    await self._settle(delivery, "failed", error_code="invalid_chat_id")
                    return
                message_id = await self.max_client.send_text(
                    delivery.text, chat_id=int(delivery.chat_id)
                )
        except (httpx.TimeoutException, httpx.TransportError):
            # MAX мог принять сообщение до разрыва соединения; повтор может создать дубль.
            await self._settle(delivery, "delivery_unknown", error_code="transport_uncertain")
            return
        except MaxApiError as exc:
            if exc.status_code == 403:
                await self._settle(delivery, "unreachable", error_code=exc.code or "forbidden")
            elif exc.status_code == 429 or exc.status_code >= 500:
                await self._retry(delivery, exc.code or f"http_{exc.status_code}")
            elif exc.status_code == 200:
                await self._settle(delivery, "delivery_unknown", error_code=exc.code)
            else:
                await self._settle(delivery, "failed", error_code=exc.code or "max_rejected")
            return
        await self._settle(delivery, "sent", max_message_id=message_id)

    async def _retry(self, delivery: PendingDelivery, error_code: str) -> None:
        if delivery.attempts >= self.max_attempts:
            await self._settle(delivery, "dead", error_code=error_code)
            return
        delay = timedelta(seconds=min(60, 5 * (2 ** (delivery.attempts - 1))))
        await self._settle(delivery, "pending", error_code=error_code, retry_after=delay)

    async def _settle(
        self,
        delivery: PendingDelivery,
        status: str,
        *,
        max_message_id: str | None = None,
        error_code: str | None = None,
        retry_after: timedelta | None = None,
    ) -> None:
        async with self.sessions.begin() as session:
            await PostgresDeliveryQueue(session, self.clock).settle(
                delivery.id,
                self.worker_id,
                self.clock.now(),
                status,
                max_message_id=max_message_id,
                error_code=error_code,
                retry_after=retry_after,
            )
        logger.info(
            "delivery_settled",
            delivery_id=str(delivery.id),
            house_id=str(delivery.house_id),
            status=status,
            error_code=error_code,
        )
