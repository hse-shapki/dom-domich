"""Удаление персонального payload после срока; metadata очередей остаётся для аудита."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.infrastructure.postgres.models import InboxEventRow, OutboxDeliveryRow


@dataclass(frozen=True, slots=True)
class RedactionResult:
    inbox_events: int
    outbox_deliveries: int


async def redact_expired_payloads(session: AsyncSession, before: datetime) -> RedactionResult:
    if before.tzinfo is None:
        raise ValueError("retention boundary must be timezone-aware")
    inbox_result = await session.scalars(
        update(InboxEventRow)
        .where(
            InboxEventRow.received_at < before,
            InboxEventRow.status.in_(("done", "ignored")),
            InboxEventRow.raw_update["redacted"].as_boolean().is_not(True),
        )
        .values(
            raw_update={"redacted": True, "reason": "retention_expired"},
            normalized_event=None,
        )
        .returning(InboxEventRow.id)
    )
    outbox_result = await session.scalars(
        update(OutboxDeliveryRow)
        .where(
            OutboxDeliveryRow.available_at < before,
            OutboxDeliveryRow.status.in_(
                ("sent", "unreachable", "failed", "dead", "delivery_unknown", "superseded")
            ),
            OutboxDeliveryRow.text != "[удалено по сроку хранения]",
        )
        .values(text="[удалено по сроку хранения]")
        .returning(OutboxDeliveryRow.id)
    )
    return RedactionResult(len(tuple(inbox_result)), len(tuple(outbox_result)))
