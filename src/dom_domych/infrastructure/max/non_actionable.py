"""Явное завершение MAX-событий, которые MVP хранит для аудита, но не применяет."""

import structlog

from dom_domych.contracts.events import EventEnvelope, EventName, EventSource

logger = structlog.get_logger()

_NON_ACTIONABLE = frozenset(
    {
        EventName.MESSAGE_EDITED,
        EventName.MESSAGE_REMOVED,
        EventName.ATTACHMENT_RECEIVED,
        EventName.HOUSE_BOT_MEMBERSHIP_CHANGED,
        EventName.HOUSE_BOT_PERMISSIONS_CHANGED,
    }
)


class MaxNonActionableEventHandler:
    """Не скрывает ошибки business handlers и не пишет payload/ID в публичный лог."""

    async def __call__(self, event: EventEnvelope) -> bool:
        if event.source is not EventSource.MAX or event.name not in _NON_ACTIONABLE:
            return False
        logger.info("max_event_recorded_without_action", name=event.name.value)
        return True
