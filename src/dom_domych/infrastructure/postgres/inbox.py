"""Короткая транзакционная запись входящих событий; worker не запускается в HTTP request."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.contracts.events import EventEnvelope, EventSource
from dom_domych.infrastructure.postgres.models import InboxEventRow


async def save_inbox_event(
    session: AsyncSession,
    source_key: str,
    event: EventEnvelope | None,
    raw_update: dict[str, object],
    received_at: datetime,
) -> bool:
    """True означает новую запись; duplicate подтверждается без второго события."""

    statement = (
        insert(InboxEventRow)
        .values(
            id=event.event_id if event is not None else uuid4(),
            source="max",
            source_key=source_key,
            event_name=event.name if event is not None else None,
            house_id=event.house_id if event is not None else None,
            raw_update=raw_update,
            normalized_event=event.model_dump(mode="json") if event is not None else None,
            received_at=received_at,
            available_at=received_at,
            status="pending" if event is not None else "ignored",
        )
        .on_conflict_do_nothing(index_elements=["source", "source_key"])
        .returning(InboxEventRow.id)
    )
    return (await session.scalar(statement)) is not None


async def save_domain_event(session: AsyncSession, event: EventEnvelope) -> bool:
    """В той же UoW сохраняет внутреннее событие для inbox worker."""

    if event.house_id is None or event.entity is None or event.source is not EventSource.DOMAIN:
        raise ValueError("DOMAIN_EVENT_REQUIRED")
    statement = (
        insert(InboxEventRow)
        .values(
            id=event.event_id,
            source="domain",
            source_key=event.source_key,
            event_name=event.name,
            house_id=event.house_id,
            raw_update={},
            normalized_event=event.model_dump(mode="json"),
            received_at=event.received_at,
            available_at=event.received_at,
            status="pending",
        )
        .on_conflict_do_nothing(index_elements=["source", "source_key"])
        .returning(InboxEventRow.id)
    )
    return (await session.scalar(statement)) is not None
