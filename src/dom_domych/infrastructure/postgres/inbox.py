"""Короткая транзакционная запись входящих событий; worker не запускается в HTTP request."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.contracts.events import EventEnvelope
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
