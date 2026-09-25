"""Транзакционный JobPort и lease для таймеров."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.contracts.events import EventName
from dom_domych.domain.ports.core import JobIntent
from dom_domych.infrastructure.postgres.models import ScheduledJobRow


class JobConflictError(ValueError):
    pass


class JobLeaseLostError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DueJob:
    id: UUID
    house_id: UUID
    event_name: EventName
    entity_id: UUID
    expected_version: int
    due_at: datetime
    attempts: int


class PostgresJobQueue:
    """enqueue использует общую AsyncSession use case, без собственного commit."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(self, intent: JobIntent) -> UUID:
        if not intent.operation_key or intent.expected_version < 1:
            raise ValueError("job needs operation key and positive expected version")
        if intent.due_at.tzinfo is None or intent.due_at.utcoffset() != timedelta(0):
            raise ValueError("job deadline must be UTC")
        event_name = EventName(intent.event_name)
        if event_name in {
            EventName.MESSAGE_RECEIVED,
            EventName.MESSAGE_EDITED,
            EventName.MESSAGE_REMOVED,
            EventName.ATTACHMENT_RECEIVED,
            EventName.CALLBACK_RECEIVED,
            EventName.BOT_STARTED,
            EventName.BOT_STOPPED,
            EventName.HOUSE_BOT_MEMBERSHIP_CHANGED,
            EventName.HOUSE_BOT_PERMISSIONS_CHANGED,
        }:
            raise ValueError("ingress event cannot be scheduled")
        job_id = uuid4()
        inserted_id = await self.session.scalar(
            insert(ScheduledJobRow)
            .values(
                id=job_id,
                house_id=intent.house_id,
                operation_key=intent.operation_key,
                event_name=event_name.value,
                entity_id=intent.entity_id,
                expected_version=intent.expected_version,
                due_at=intent.due_at,
                available_at=intent.due_at,
                status="pending",
            )
            .on_conflict_do_nothing(index_elements=["house_id", "operation_key"])
            .returning(ScheduledJobRow.id)
        )
        if inserted_id is not None:
            return inserted_id
        existing = await self.session.scalar(
            select(ScheduledJobRow).where(
                ScheduledJobRow.house_id == intent.house_id,
                ScheduledJobRow.operation_key == intent.operation_key,
            )
        )
        if existing is None:
            raise RuntimeError("conflicting job disappeared")
        if (
            existing.event_name,
            existing.entity_id,
            existing.expected_version,
            existing.due_at,
        ) != (event_name.value, intent.entity_id, intent.expected_version, intent.due_at):
            raise JobConflictError("operation_key reused for different job")
        return existing.id

    async def claim(self, worker_id: str, now: datetime, lease_for: timedelta) -> DueJob | None:
        row = await self.session.scalar(
            select(ScheduledJobRow)
            .where(
                ScheduledJobRow.due_at <= now,
                or_(
                    and_(ScheduledJobRow.status == "pending", ScheduledJobRow.available_at <= now),
                    and_(
                        ScheduledJobRow.status == "processing", ScheduledJobRow.lease_until <= now
                    ),
                ),
            )
            .order_by(ScheduledJobRow.due_at, ScheduledJobRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        row.status = "processing"
        row.attempts += 1
        row.lease_owner = worker_id
        row.lease_until = now + lease_for
        return DueJob(
            row.id,
            row.house_id,
            EventName(row.event_name),
            row.entity_id,
            row.expected_version,
            row.due_at,
            row.attempts,
        )

    async def settle(
        self,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        status: str,
        *,
        error_code: str | None = None,
        retry_after: timedelta | None = None,
    ) -> None:
        values: dict[str, object] = {
            "status": status,
            "lease_owner": None,
            "lease_until": None,
            "error_code": error_code,
        }
        if retry_after is not None:
            values["available_at"] = now + retry_after
        result = await self.session.scalar(
            update(ScheduledJobRow)
            .where(
                ScheduledJobRow.id == job_id,
                ScheduledJobRow.status == "processing",
                ScheduledJobRow.lease_owner == worker_id,
                ScheduledJobRow.lease_until > now,
            )
            .values(**values)
            .returning(ScheduledJobRow.id)
        )
        if result is None:
            raise JobLeaseLostError("job lease has expired or changed owner")

    async def heartbeat(
        self, job_id: UUID, worker_id: str, now: datetime, lease_for: timedelta
    ) -> None:
        renewed = await self.session.scalar(
            update(ScheduledJobRow)
            .where(
                ScheduledJobRow.id == job_id,
                ScheduledJobRow.status == "processing",
                ScheduledJobRow.lease_owner == worker_id,
                ScheduledJobRow.lease_until > now,
            )
            .values(lease_until=now + lease_for)
            .returning(ScheduledJobRow.id)
        )
        if renewed is None:
            raise JobLeaseLostError("job lease has expired or changed owner")
