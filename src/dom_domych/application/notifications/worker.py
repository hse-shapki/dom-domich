"""Отправка намерений outbox после commit бизнес-транзакции."""

import asyncio
from datetime import timedelta
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.files.local import FileKind, FileStoreError, LocalFileStore
from dom_domych.infrastructure.max.client import MaxApiClient, MaxApiError
from dom_domych.infrastructure.max.media import MaxMediaError, MaxMediaHttpError, MaxMediaTransport
from dom_domych.infrastructure.postgres.delivery import (
    DeliveryLeaseLostError,
    PendingDelivery,
    PostgresDeliveryQueue,
)

logger = structlog.get_logger()


class DeliveryWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        max_client: MaxApiClient,
        clock: Clock,
        worker_id: str,
        max_attempts: int = 5,
        media: MaxMediaTransport | None = None,
        files: LocalFileStore | None = None,
        lease_for: timedelta = timedelta(seconds=60),
    ) -> None:
        if max_attempts < 1 or lease_for <= timedelta(0):
            raise ValueError("max_attempts must be positive")
        self.sessions = sessions
        self.max_client = max_client
        self.clock = clock
        self.worker_id = worker_id
        self.max_attempts = max_attempts
        self.media = media
        self.files = files
        self.lease_for = lease_for

    async def run_once(self) -> bool:
        async with self.sessions.begin() as session:
            delivery = await PostgresDeliveryQueue(session, self.clock).claim(
                self.worker_id, self.clock.now(), self.lease_for
            )
        if delivery is None:
            return False
        heartbeat = asyncio.create_task(self._heartbeat(delivery.id))
        try:
            await self._deliver(delivery)
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
        return True

    async def _heartbeat(self, delivery_id: UUID) -> None:
        interval = self.lease_for.total_seconds() / 3
        while True:
            await asyncio.sleep(interval)
            async with self.sessions.begin() as session:
                try:
                    await PostgresDeliveryQueue(session, self.clock).heartbeat(
                        delivery_id,
                        self.worker_id,
                        self.clock.now(),
                        self.lease_for,
                    )
                except DeliveryLeaseLostError:
                    return

    async def _deliver(self, delivery: PendingDelivery) -> None:
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
        if delivery.file_key is not None and delivery.edit_key is not None:
            await self._settle(delivery, "failed", error_code="file_edit_unsupported")
            return
        attachments: list[dict[str, object]] | None = None
        if delivery.file_key is not None:
            if self.media is None or self.files is None:
                await self._settle(
                    delivery, "waiting_attachment", error_code="attachment_transport_missing"
                )
                return
            try:
                token = await self._attachment_token(delivery)
            except (httpx.TimeoutException, httpx.TransportError):
                await self._retry(delivery, "upload_transport_error")
                return
            except MaxMediaHttpError as exc:
                if exc.status_code == 429 or exc.status_code >= 500:
                    await self._retry(delivery, f"upload_http_{exc.status_code}")
                else:
                    await self._settle(delivery, "failed", error_code="upload_rejected")
                return
            except MaxApiError as exc:
                if exc.status_code == 429 or exc.status_code >= 500:
                    await self._retry(delivery, exc.code or "upload_slot_retry")
                else:
                    await self._settle(delivery, "failed", error_code=exc.code or "upload_slot")
                return
            except (MaxMediaError, FileStoreError) as exc:
                await self._settle(delivery, "failed", error_code=type(exc).__name__)
                return
            attachments = [{"type": "file", "payload": {"token": token}}]
        try:
            if edit_message_id is not None:
                await self.max_client.edit_text(
                    edit_message_id,
                    delivery.text,
                    dialog_key=(
                        f"chat:{delivery.chat_id}"
                        if delivery.chat_id is not None
                        else f"resident:{delivery.recipient_id}"
                    ),
                )
                message_id = edit_message_id
            elif user_id is not None:
                message_id = await self.max_client.send_text(
                    delivery.text, user_id=user_id, attachments=attachments
                )
            else:
                assert delivery.chat_id is not None
                if not delivery.chat_id.isdecimal():
                    await self._settle(delivery, "failed", error_code="invalid_chat_id")
                    return
                message_id = await self.max_client.send_text(
                    delivery.text, chat_id=int(delivery.chat_id), attachments=attachments
                )
        except (httpx.TimeoutException, httpx.TransportError):
            # MAX мог принять сообщение до разрыва соединения; повтор может создать дубль.
            await self._settle(delivery, "delivery_unknown", error_code="transport_uncertain")
            return
        except MaxApiError as exc:
            if exc.code == "attachment.not.ready":
                await self._retry(delivery, exc.code)
            elif exc.status_code == 403:
                await self._settle(delivery, "unreachable", error_code=exc.code or "forbidden")
            elif exc.status_code == 429 or exc.status_code >= 500:
                await self._retry(delivery, exc.code or f"http_{exc.status_code}")
            elif exc.status_code == 200:
                await self._settle(delivery, "delivery_unknown", error_code=exc.code)
            else:
                await self._settle(delivery, "failed", error_code=exc.code or "max_rejected")
            return
        await self._settle(delivery, "sent", max_message_id=message_id)

    async def _attachment_token(self, delivery: PendingDelivery) -> str:
        if delivery.attachment_token is not None:
            return delivery.attachment_token
        assert self.files is not None and self.media is not None and delivery.file_key is not None
        stored, content = await self.files.get(delivery.house_id, delivery.file_key)
        if stored.kind is not FileKind.DOCUMENT or stored.mime_type != "application/pdf":
            raise MaxMediaError("outbox file is not a PDF document")
        token = await self.media.upload_pdf(content, f"dom-domych-{delivery.file_key}.pdf")
        async with self.sessions.begin() as session:
            await PostgresDeliveryQueue(session, self.clock).save_attachment_token(
                delivery.id, self.worker_id, self.clock.now(), token
            )
        return token

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
