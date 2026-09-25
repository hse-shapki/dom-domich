"""Транзакционный DeliveryPort и хранение результатов отправки."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.domain.ports.core import Clock, DeliveryIntent
from dom_domych.infrastructure.postgres.models import (
    HouseRow,
    OutboxDeliveryRow,
    ResidencyRow,
    ResidentRow,
)


class DeliveryConflictError(ValueError):
    pass


class DeliveryLeaseLostError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PendingDelivery:
    id: UUID
    house_id: UUID
    operation_key: str
    text: str
    recipient_id: UUID | None
    chat_id: str | None
    edit_key: str | None
    file_key: UUID | None
    attachment_token: str | None
    attempts: int


class PostgresDeliveryQueue:
    """Использует session вызывающей UoW; enqueue не делает commit и не вызывает MAX."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    async def enqueue(self, intent: DeliveryIntent) -> UUID:
        if not intent.operation_key or not intent.text and intent.file_key is None:
            raise ValueError("delivery needs operation_key and content")
        if (intent.recipient_id is None) == (intent.chat_id is None):
            raise ValueError("delivery needs exactly one target")
        if intent.chat_id is not None:
            mapped_house = await self.session.scalar(
                select(HouseRow.id).where(HouseRow.max_chat_id == intent.chat_id)
            )
            if mapped_house != intent.house_id:
                raise ValueError("chat does not belong to house")
        if intent.edit_key is not None:
            target = await self.session.scalar(
                select(OutboxDeliveryRow)
                .where(
                    OutboxDeliveryRow.house_id == intent.house_id,
                    OutboxDeliveryRow.operation_key == intent.edit_key,
                )
                .with_for_update()
            )
            if target is None or target.chat_id != intent.chat_id:
                raise ValueError("edit target does not belong to delivery chat")
            existing_edit = await self.session.scalar(
                select(OutboxDeliveryRow).where(
                    OutboxDeliveryRow.house_id == intent.house_id,
                    OutboxDeliveryRow.operation_key == intent.operation_key,
                )
            )
            if existing_edit is not None:
                self._validate_existing(existing_edit, intent)
                return existing_edit.id
            await self.session.execute(
                update(OutboxDeliveryRow)
                .where(
                    OutboxDeliveryRow.house_id == intent.house_id,
                    OutboxDeliveryRow.edit_key == intent.edit_key,
                    OutboxDeliveryRow.status == "pending",
                )
                .values(status="superseded", error_code="coalesced_by_newer_edit")
            )
        delivery_id = uuid4()
        inserted_id = await self.session.scalar(
            insert(OutboxDeliveryRow)
            .values(
                id=delivery_id,
                house_id=intent.house_id,
                operation_key=intent.operation_key,
                text=intent.text,
                recipient_id=intent.recipient_id,
                chat_id=intent.chat_id,
                edit_key=intent.edit_key,
                file_key=intent.file_key,
                status="pending",
                available_at=self.clock.now(),
            )
            .on_conflict_do_nothing(index_elements=["house_id", "operation_key"])
            .returning(OutboxDeliveryRow.id)
        )
        if inserted_id is not None:
            return inserted_id
        existing = await self.session.scalar(
            select(OutboxDeliveryRow).where(
                OutboxDeliveryRow.house_id == intent.house_id,
                OutboxDeliveryRow.operation_key == intent.operation_key,
            )
        )
        if existing is None:
            raise RuntimeError("conflicting delivery disappeared")
        self._validate_existing(existing, intent)
        return existing.id

    @staticmethod
    def _validate_existing(existing: OutboxDeliveryRow, intent: DeliveryIntent) -> None:
        if (
            existing.text,
            existing.recipient_id,
            existing.chat_id,
            existing.edit_key,
            existing.file_key,
        ) != (
            intent.text,
            intent.recipient_id,
            intent.chat_id,
            intent.edit_key,
            intent.file_key,
        ):
            raise DeliveryConflictError("operation_key reused for different delivery")

    async def claim(
        self, worker_id: str, now: datetime, lease_for: timedelta
    ) -> PendingDelivery | None:
        row = await self.session.scalar(
            select(OutboxDeliveryRow)
            .where(
                or_(
                    and_(
                        OutboxDeliveryRow.status == "pending", OutboxDeliveryRow.available_at <= now
                    ),
                    and_(
                        OutboxDeliveryRow.status == "processing",
                        OutboxDeliveryRow.lease_until <= now,
                    ),
                )
            )
            .order_by(OutboxDeliveryRow.available_at, OutboxDeliveryRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        row.status = "processing"
        row.attempts += 1
        row.lease_owner = worker_id
        row.lease_until = now + lease_for
        return PendingDelivery(
            row.id,
            row.house_id,
            row.operation_key,
            row.text,
            row.recipient_id,
            row.chat_id,
            row.edit_key,
            row.file_key,
            row.attachment_token,
            row.attempts,
        )

    async def save_attachment_token(
        self, delivery_id: UUID, worker_id: str, now: datetime, token: str
    ) -> None:
        if not token:
            raise ValueError("MAX attachment token required")
        result = await self.session.scalar(
            update(OutboxDeliveryRow)
            .where(
                OutboxDeliveryRow.id == delivery_id,
                OutboxDeliveryRow.status == "processing",
                OutboxDeliveryRow.lease_owner == worker_id,
                OutboxDeliveryRow.lease_until > now,
            )
            .values(attachment_token=token)
            .returning(OutboxDeliveryRow.id)
        )
        if result is None:
            raise DeliveryLeaseLostError("outbox lease has expired or changed owner")

    async def heartbeat(
        self, delivery_id: UUID, worker_id: str, now: datetime, lease_for: timedelta
    ) -> None:
        renewed = await self.session.scalar(
            update(OutboxDeliveryRow)
            .where(
                OutboxDeliveryRow.id == delivery_id,
                OutboxDeliveryRow.status == "processing",
                OutboxDeliveryRow.lease_owner == worker_id,
                OutboxDeliveryRow.lease_until > now,
            )
            .values(lease_until=now + lease_for)
            .returning(OutboxDeliveryRow.id)
        )
        if renewed is None:
            raise DeliveryLeaseLostError("outbox lease has expired or changed owner")

    async def resolve_target(self, delivery: PendingDelivery, now: datetime) -> int | None:
        if delivery.recipient_id is None:
            return None
        result = await self.session.scalar(
            select(ResidentRow.max_user_id)
            .join(ResidencyRow, ResidencyRow.resident_id == ResidentRow.id)
            .where(
                ResidentRow.id == delivery.recipient_id,
                ResidentRow.dm_reachable.is_(True),
                ResidencyRow.house_id == delivery.house_id,
                ResidencyRow.confirmed.is_(True),
                ResidencyRow.valid_from <= now,
                or_(ResidencyRow.valid_until.is_(None), ResidencyRow.valid_until > now),
            )
            .limit(1)
        )
        return int(result) if result is not None and result.isdecimal() else None

    async def edit_message_id(self, delivery: PendingDelivery) -> str | None:
        if delivery.edit_key is None:
            return None
        return await self.session.scalar(
            select(OutboxDeliveryRow.max_message_id).where(
                OutboxDeliveryRow.house_id == delivery.house_id,
                OutboxDeliveryRow.operation_key == delivery.edit_key,
                OutboxDeliveryRow.status == "sent",
            )
        )

    async def settle(
        self,
        delivery_id: UUID,
        worker_id: str,
        now: datetime,
        status: str,
        *,
        max_message_id: str | None = None,
        error_code: str | None = None,
        retry_after: timedelta | None = None,
    ) -> None:
        values: dict[str, object] = {
            "status": status,
            "lease_owner": None,
            "lease_until": None,
            "max_message_id": max_message_id,
            "error_code": error_code,
        }
        if retry_after is not None:
            values["available_at"] = now + retry_after
        settled = await self.session.scalar(
            update(OutboxDeliveryRow)
            .where(
                OutboxDeliveryRow.id == delivery_id,
                OutboxDeliveryRow.status == "processing",
                OutboxDeliveryRow.lease_owner == worker_id,
                OutboxDeliveryRow.lease_until > now,
            )
            .values(**values)
            .returning(OutboxDeliveryRow.id)
        )
        if settled is None:
            raise DeliveryLeaseLostError("outbox lease has expired or changed owner")
