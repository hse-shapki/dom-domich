"""Claim/heartbeat/finish для durable inbox без транзакции во время handler."""

import json
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.contracts.events import EventEnvelope
from dom_domych.infrastructure.postgres.models import InboxEventRow


class LeaseLostError(RuntimeError):
    pass


class InboxStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(
        self, worker_id: str, now: datetime, lease_for: timedelta
    ) -> EventEnvelope | None:
        candidate = await self.session.scalar(
            select(InboxEventRow)
            .where(
                or_(
                    and_(InboxEventRow.status == "pending", InboxEventRow.available_at <= now),
                    and_(
                        InboxEventRow.status == "processing",
                        InboxEventRow.lease_until <= now,
                    ),
                )
            )
            .order_by(InboxEventRow.received_at, InboxEventRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if candidate is None:
            return None
        candidate.status = "processing"
        candidate.attempts += 1
        candidate.lease_owner = worker_id
        candidate.lease_until = now + lease_for
        if candidate.normalized_event is None:
            raise ValueError("pending inbox entry lacks normalized event")
        return EventEnvelope.model_validate_json(json.dumps(candidate.normalized_event))

    async def heartbeat(
        self, event_id: UUID, worker_id: str, now: datetime, lease_for: timedelta
    ) -> None:
        statement = (
            update(InboxEventRow)
            .where(
                InboxEventRow.id == event_id,
                InboxEventRow.status == "processing",
                InboxEventRow.lease_owner == worker_id,
                InboxEventRow.lease_until > now,
            )
            .values(lease_until=now + lease_for)
            .returning(InboxEventRow.id)
        )
        if await self.session.scalar(statement) is None:
            raise LeaseLostError("inbox lease has expired or changed owner")

    async def finish(self, event_id: UUID, worker_id: str, now: datetime) -> None:
        statement = (
            update(InboxEventRow)
            .where(
                InboxEventRow.id == event_id,
                InboxEventRow.status == "processing",
                InboxEventRow.lease_owner == worker_id,
                InboxEventRow.lease_until > now,
            )
            .values(status="done", lease_owner=None, lease_until=None)
            .returning(InboxEventRow.id)
        )
        if await self.session.scalar(statement) is None:
            raise LeaseLostError("inbox lease has expired or changed owner")

    async def fail(
        self,
        event_id: UUID,
        worker_id: str,
        now: datetime,
        retry_after: timedelta,
        max_attempts: int,
    ) -> str:
        row = await self.session.scalar(
            select(InboxEventRow)
            .where(InboxEventRow.id == event_id, InboxEventRow.lease_owner == worker_id)
            .with_for_update()
        )
        if row is None or row.status != "processing" or row.lease_until is None:
            raise LeaseLostError("inbox lease has expired or changed owner")
        if row.lease_until <= now:
            raise LeaseLostError("inbox lease has expired or changed owner")
        row.status = "dead" if row.attempts >= max_attempts else "pending"
        row.available_at = now + retry_after
        row.lease_owner = None
        row.lease_until = None
        return row.status
