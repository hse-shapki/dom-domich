"""A10: actor из MAX callback, серверные tokens и права реестра."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update

from dom_domych.application.polls.callback import (
    CallbackInput,
    CallbackOutcome,
    CallbackStatus,
    StoredPollAction,
)
from dom_domych.application.polls.max_callback import (
    MaxPollCallbackTransport,
    ResolvedCallbackContext,
)
from dom_domych.contracts.events import CallbackPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.polls.models import VoteChoice
from dom_domych.infrastructure.max.client import MaxApiClient
from dom_domych.infrastructure.postgres.models import HouseRow, PollActionRow, ResidentRow
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore, token_digest
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO, synthetic_id


class RecordingProcessor:
    def __init__(self) -> None:
        self.calls: list[tuple[CallbackInput, ResolvedCallbackContext]] = []

    async def handle(
        self, callback: CallbackInput, context: ResolvedCallbackContext
    ) -> CallbackOutcome:
        self.calls.append((callback, context))
        return CallbackOutcome(CallbackStatus.RECORDED)


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("A10 requires dedicated migrated PostgreSQL test database")
    return value


def callback_event(token: str, user_id: str, chat_id: str | None = None) -> EventEnvelope:
    event_id = uuid4()
    now = datetime(2026, 9, 25, 12, tzinfo=UTC)
    return EventEnvelope(
        event_id=event_id,
        source=EventSource.MAX,
        source_key=f"message_callback:{event_id}",
        name=EventName.CALLBACK_RECEIVED,
        occurred_at=now,
        received_at=now,
        correlation_id=event_id,
        actor_user_id=user_id,
        callback=CallbackPayload(
            callback_id=f"callback-{event_id}",
            sender_user_id=user_id,
            action_token=token,
            chat_id=chat_id,
        ),
    )


@pytest.mark.asyncio
async def test_max_callback_uses_registry_actor_and_rejects_wrong_house_or_resident() -> None:
    resident_id = synthetic_id("resident-2")
    unconfirmed_id = synthetic_id("resident-13")
    poll_id = uuid4()
    action = StoredPollAction(
        poll_id=poll_id,
        house_id=HOUSE_ONE,
        audience_id=uuid4(),
        subject_revision=1,
        choice=VoteChoice.YES,
        expires_at=datetime(2026, 9, 25, 13, tzinfo=UTC),
        bound_resident_id=resident_id,
    )
    processor = RecordingProcessor()
    acknowledged: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        acknowledged.append(request.url.params["callback_id"])
        return httpx.Response(200, json={"success": True})

    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(ResidentRow).where(ResidentRow.id == resident_id).values(max_user_id="222")
            )
            await session.execute(
                update(ResidentRow)
                .where(ResidentRow.id == unconfirmed_id)
                .values(max_user_id="313")
            )
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id="333")
            )
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_TWO).values(max_chat_id="444")
            )
            token = await PostgresPollActionStore(session).create(action)
        async with sessions() as session:
            stored = await session.scalar(
                select(PollActionRow).where(PollActionRow.token_digest == token_digest(token))
            )
            assert stored is not None and stored.token_digest != token
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
        ) as http:
            async with sessions() as session:
                transport = MaxPollCallbackTransport(
                    session,
                    PostgresPollActionStore(session),
                    processor,
                    MaxApiClient(http, "test-token"),
                )
                good = callback_event(token, "222", "333")
                assert (await transport.handle(good)).status is CallbackStatus.RECORDED
                assert (
                    await transport.handle(callback_event(token, "313", "333"))
                ).status is CallbackStatus.NOT_ALLOWED
                assert (
                    await transport.handle(callback_event(token, "222", "444"))
                ).status is CallbackStatus.NOT_ALLOWED
                assert (
                    await transport.handle(callback_event("unknown", "222"))
                ).status is CallbackStatus.UNKNOWN_ACTION
        assert len(processor.calls) == 1
        assert processor.calls[0][0].source_event_id == good.event_id
        assert processor.calls[0][1] == ResolvedCallbackContext(HOUSE_ONE, resident_id)
        assert len(acknowledged) == 4
        async with sessions.begin() as session:
            await PostgresPollActionStore(session).revoke_poll(poll_id, HOUSE_ONE)
            assert (await PostgresPollActionStore(session).get(token)).revoked is True
            await session.execute(delete(PollActionRow).where(PollActionRow.poll_id == poll_id))
            await session.execute(
                update(ResidentRow)
                .where(ResidentRow.id.in_([resident_id, unconfirmed_id]))
                .values(max_user_id=None)
            )
            await session.execute(
                update(HouseRow)
                .where(HouseRow.id.in_([HOUSE_ONE, HOUSE_TWO]))
                .values(max_chat_id=None)
            )
