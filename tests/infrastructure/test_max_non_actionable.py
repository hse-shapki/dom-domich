"""Recognized MAX audit events settle without pretending to perform a domain action."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from dom_domych.contracts.events import (
    EventEnvelope,
    EventName,
    EventSource,
    HouseBotPayload,
    MessagePayload,
)
from dom_domych.infrastructure.max.non_actionable import MaxNonActionableEventHandler

NOW = datetime(2026, 9, 30, 16, tzinfo=UTC)


def _message_event(name: EventName) -> EventEnvelope:
    event_id = uuid4()
    return EventEnvelope(
        event_id=event_id,
        source=EventSource.MAX,
        source_key=f"test:{event_id}",
        name=name,
        occurred_at=NOW,
        received_at=NOW,
        correlation_id=event_id,
        actor_user_id="42",
        message=MessagePayload(
            chat_id="-9007199254740993",
            message_id="mid.test",
            sender_user_id="42",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [EventName.MESSAGE_EDITED, EventName.MESSAGE_REMOVED, EventName.ATTACHMENT_RECEIVED],
)
async def test_non_actionable_message_events_are_explicitly_accepted(name: EventName) -> None:
    assert await MaxNonActionableEventHandler()(_message_event(name))


@pytest.mark.asyncio
async def test_actionable_message_is_not_swallowed() -> None:
    assert not await MaxNonActionableEventHandler()(_message_event(EventName.MESSAGE_RECEIVED))


@pytest.mark.asyncio
async def test_permission_change_is_recorded_without_action() -> None:
    event_id = uuid4()
    event = EventEnvelope(
        event_id=event_id,
        source=EventSource.MAX,
        source_key=f"permissions:{event_id}",
        name=EventName.HOUSE_BOT_PERMISSIONS_CHANGED,
        occurred_at=NOW,
        received_at=NOW,
        correlation_id=event_id,
        actor_user_id="42",
        house_bot=HouseBotPayload(
            chat_id="-9007199254740993",
            changed_by_user_id="42",
            is_channel=False,
            change="permissions",
            bot_id="7",
            is_admin=False,
        ),
    )

    assert await MaxNonActionableEventHandler()(event)
