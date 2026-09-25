"""A04: ASGI ingress + PostgreSQL inbox по схеме MAX Update."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from dom_domych.contracts.events import EventName
from dom_domych.entrypoints.api import create_app
from dom_domych.infrastructure.max.updates import normalize_update
from dom_domych.infrastructure.postgres.models import InboxEventRow
from dom_domych.infrastructure.postgres.session import database_lifespan


def message_update(message_id: str) -> dict[str, object]:
    return {
        "update_type": "message_created",
        "timestamp": 1790326800000,
        "message": {
            "sender": {"user_id": 9007199254740993},
            "recipient": {"chat_id": 12345, "chat_type": "chat"},
            "timestamp": 1790326800000,
            "body": {"mid": message_id, "text": "Нет воды на пятом этаже"},
        },
    }


def test_normalize_callback_uses_real_max_actor() -> None:
    callback = {
        "update_type": "message_callback",
        "timestamp": 1790326800000,
        "callback": {
            "callback_id": "callback-a04",
            "payload": "opaque-action",
            "timestamp": 1790326800000,
            "user": {"user_id": 9007199254740993},
        },
        "message": None,
    }
    key, event = normalize_update(callback, datetime.now(UTC))
    assert key == "message_callback:callback-a04"
    assert event is not None
    assert event.name is EventName.CALLBACK_RECEIVED
    assert event.actor_user_id == "9007199254740993"
    assert event.callback is not None
    assert event.callback.action_token == "opaque-action"


@pytest.mark.parametrize(
    ("update_type", "change"), (("bot_added", "added"), ("bot_removed", "removed"))
)
def test_normalize_bot_membership_change(update_type: str, change: str) -> None:
    raw = {
        "update_type": update_type,
        "timestamp": 1790326800000,
        "chat_id": 12345,
        "user": {"user_id": 9007199254740993},
        "is_channel": False,
    }

    key, event = normalize_update(raw, datetime.now(UTC))

    assert key == f"{update_type}:12345:1790326800000"
    assert event is not None
    assert event.name is EventName.HOUSE_BOT_MEMBERSHIP_CHANGED
    assert event.house_bot is not None
    assert event.house_bot.change == change
    assert event.house_bot.changed_by_user_id == "9007199254740993"


def test_normalize_bot_permission_change_preserves_bot_and_permissions() -> None:
    raw = {
        "update_type": "bot_admin_permissions_changed",
        "timestamp": 1790326800000,
        "chat_id": 12345,
        "user_id": 77,
        "bot_id": 88,
        "is_channel": False,
        "is_admin": True,
        "permissions": ["read_all_messages", "write"],
    }

    key, event = normalize_update(raw, datetime.now(UTC))

    assert key == "bot_admin_permissions_changed:12345:88:1790326800000"
    assert event is not None
    assert event.name is EventName.HOUSE_BOT_PERMISSIONS_CHANGED
    assert event.house_bot is not None
    assert event.house_bot.bot_id == "88"
    assert event.house_bot.is_admin is True
    assert event.house_bot.permissions == ("read_all_messages", "write")


@pytest.mark.asyncio
async def test_webhook_commits_once_before_ack_and_rejects_bad_secret() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    app = create_app(database_url, "test-secret")
    message_id = f"mid.{uuid4().hex}"
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/ready")).status_code == 200
            bad = await client.post("/webhook/max", json=message_update(message_id))
            assert bad.status_code == 401
            headers = {"X-Max-Bot-Api-Secret": "test-secret"}
            first = await client.post(
                "/webhook/max", json=message_update(message_id), headers=headers
            )
            second = await client.post(
                "/webhook/max", json=message_update(message_id), headers=headers
            )
            assert first.json() == {"accepted": True, "new": True}
            assert second.json() == {"accepted": True, "new": False}

    async with database_lifespan(database_url) as sessions:
        async with sessions() as session:
            rows = (
                await session.scalars(
                    select(InboxEventRow).where(
                        InboxEventRow.source_key == f"message_created:12345:{message_id}"
                    )
                )
            ).all()
            assert len(rows) == 1
            assert rows[0].status == "pending"
            assert rows[0].normalized_event is not None
            assert rows[0].raw_update["update_type"] == "message_created"


@pytest.mark.asyncio
async def test_unknown_update_is_recorded_without_agent_event() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    app = create_app(database_url, "test-secret")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post(
                "/webhook/max",
                json={"update_type": "future_kind", "timestamp": 1790326800000},
                headers={"X-Max-Bot-Api-Secret": "test-secret"},
            )
            assert result.status_code == 200
    async with database_lifespan(database_url) as sessions:
        async with sessions() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(InboxEventRow)
                .where(InboxEventRow.status == "ignored")
            )
            assert count is not None and count >= 1
