from datetime import UTC, datetime
from uuid import uuid4

import pytest

from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.application.jobs.scheduler import RevisionRouter
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource, MessagePayload
from dom_domych.infrastructure.postgres.jobs import DueJob


def message_event() -> EventEnvelope:
    event_id = uuid4()
    now = datetime(2026, 9, 25, 12, tzinfo=UTC)
    return EventEnvelope(
        event_id=event_id,
        source=EventSource.MAX,
        source_key=f"test:{event_id}",
        name=EventName.MESSAGE_RECEIVED,
        occurred_at=now,
        received_at=now,
        correlation_id=event_id,
        message=MessagePayload(
            chat_id="1", message_id="message-1", sender_user_id="2", text="Нет воды"
        ),
    )


@pytest.mark.asyncio
async def test_dispatcher_offers_event_to_handlers_until_one_accepts() -> None:
    calls: list[str] = []

    async def onboarding(_event: EventEnvelope) -> bool:
        calls.append("onboarding")
        return False

    async def agent(_event: EventEnvelope) -> bool:
        calls.append("agent")
        return True

    dispatcher = EventDispatcher({EventName.MESSAGE_RECEIVED: [onboarding]})
    dispatcher.register(EventName.MESSAGE_RECEIVED, agent)

    await dispatcher.handle(message_event())

    assert calls == ["onboarding", "agent"]


@pytest.mark.asyncio
async def test_dispatcher_rejects_event_when_no_handler_accepts() -> None:
    async def skip(_event: EventEnvelope) -> bool:
        return False

    with pytest.raises(LookupError):
        await EventDispatcher({EventName.MESSAGE_RECEIVED: skip}).handle(message_event())


@pytest.mark.asyncio
async def test_revision_router_selects_owner_by_event_name() -> None:
    class Reader:
        async def current_version(self, _job: DueJob) -> int:
            return 7

    now = datetime(2026, 9, 25, 12, tzinfo=UTC)
    job = DueJob(
        id=uuid4(),
        house_id=uuid4(),
        event_name=EventName.POLL_EXPIRED,
        entity_id=uuid4(),
        expected_version=7,
        due_at=now,
        attempts=1,
    )
    router = RevisionRouter()
    router.register(EventName.POLL_EXPIRED, Reader())

    assert await router.current_version(job) == 7
    with pytest.raises(ValueError):
        router.register(EventName.POLL_EXPIRED, Reader())
