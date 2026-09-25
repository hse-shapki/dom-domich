"""A08: атомарное намерение доставки, MAX send и недоступная личка."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update

from dom_domych.application.notifications.worker import DeliveryWorker
from dom_domych.domain.ports.core import DeliveryIntent
from dom_domych.infrastructure.max.client import MaxApiClient
from dom_domych.infrastructure.postgres.delivery import DeliveryConflictError, PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.models import HouseRow, OutboxDeliveryRow, ResidentRow
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("A08 requires dedicated migrated PostgreSQL test database")
    return value


@pytest.mark.asyncio
async def test_delivery_intent_commits_with_uow_and_sends_once() -> None:
    clock = FixedClock()
    key = f"a08:{uuid4()}"
    recipient_id = synthetic_id("resident-2")
    intent = DeliveryIntent(HOUSE_ONE, key, "Нет воды", recipient_id=recipient_id)
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": {"body": {"mid": "mid.1"}}})

    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(ResidentRow).where(ResidentRow.id == recipient_id).values(max_user_id="222")
            )
        async with sessions() as session:
            queued_id = await PostgresDeliveryQueue(session, clock).enqueue(intent)
            await session.rollback()
        async with sessions.begin() as session:
            assert await session.get(OutboxDeliveryRow, queued_id) is None
            queue = PostgresDeliveryQueue(session, clock)
            queued_id = await queue.enqueue(intent)
            assert await queue.enqueue(intent) == queued_id
            with pytest.raises(DeliveryConflictError):
                await queue.enqueue(
                    DeliveryIntent(HOUSE_ONE, key, "Другое", recipient_id=recipient_id)
                )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
        ) as http:
            worker = DeliveryWorker(sessions, MaxApiClient(http, "test-token"), clock, "w1")
            assert await worker.run_once()
        async with sessions.begin() as session:
            row = await session.get(OutboxDeliveryRow, queued_id)
            assert row is not None and row.status == "sent" and row.max_message_id == "mid.1"
            await session.execute(
                delete(OutboxDeliveryRow).where(OutboxDeliveryRow.id == queued_id)
            )
            await session.execute(
                update(ResidentRow).where(ResidentRow.id == recipient_id).values(max_user_id=None)
            )
    assert len(seen) == 1 and seen[0].url.params["user_id"] == "222"


@pytest.mark.asyncio
async def test_unreachable_resident_stays_in_audience_but_delivery_is_recorded() -> None:
    clock = FixedClock()
    recipient_id = synthetic_id("resident-10")
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            delivery_id = await PostgresDeliveryQueue(session, clock).enqueue(
                DeliveryIntent(HOUSE_ONE, f"a08:{uuid4()}", "Опрос", recipient_id=recipient_id)
            )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("MAX must not be called")),
            base_url="https://platform-api2.max.ru",
        ) as http:
            assert await DeliveryWorker(
                sessions, MaxApiClient(http, "test-token"), clock, "w1"
            ).run_once()
        async with sessions.begin() as session:
            row = await session.scalar(
                select(OutboxDeliveryRow).where(OutboxDeliveryRow.id == delivery_id)
            )
            assert row is not None and row.status == "unreachable"
            await session.execute(
                delete(OutboxDeliveryRow).where(OutboxDeliveryRow.id == delivery_id)
            )


@pytest.mark.asyncio
async def test_public_card_is_sent_then_edited_by_saved_message_id() -> None:
    clock = FixedClock()
    initial_key = f"a08:card:{uuid4()}"
    updates: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        updates.append(request)
        if request.method == "PUT":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"message": {"body": {"mid": "mid.card"}}})

    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id="333")
            )
            queue = PostgresDeliveryQueue(session, clock)
            first_id = await queue.enqueue(
                DeliveryIntent(HOUSE_ONE, initial_key, "Первый", chat_id="333")
            )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
        ) as http:
            worker = DeliveryWorker(sessions, MaxApiClient(http, "test-token"), clock, "w1")
            assert await worker.run_once()
            async with sessions.begin() as session:
                edit_id = await PostgresDeliveryQueue(session, clock).enqueue(
                    DeliveryIntent(
                        HOUSE_ONE,
                        f"{initial_key}:edit",
                        "Обновлён",
                        chat_id="333",
                        edit_key=initial_key,
                    )
                )
            assert await worker.run_once()
        async with sessions.begin() as session:
            edited = await session.get(OutboxDeliveryRow, edit_id)
            assert edited is not None and edited.status == "sent"
            assert edited.max_message_id == "mid.card"
            await session.execute(
                delete(OutboxDeliveryRow).where(OutboxDeliveryRow.id.in_([first_id, edit_id]))
            )
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id=None)
            )
    assert [request.method for request in updates] == ["POST", "PUT"]
    assert updates[1].url.params["message_id"] == "mid.card"
