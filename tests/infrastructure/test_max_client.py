"""A03: документированные MAX endpoints через HTTPX MockTransport."""

import json

import httpx
import pytest

from dom_domych.infrastructure.max.client import MaxApiClient, MaxApiError


@pytest.mark.asyncio
async def test_client_uses_authorization_header_and_exact_recipient() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/me":
            return httpx.Response(200, json={"user_id": 123, "is_bot": True, "username": "dom"})
        return httpx.Response(200, json={"message": {"body": {"mid": "mid.abc"}}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru", timeout=5
    ) as http:
        api = MaxApiClient(http, "secret-token")
        assert (await api.get_me()).user_id == 123
        assert await api.send_text("Нет воды", user_id=9007199254740993) == "mid.abc"
    assert seen[0].headers["Authorization"] == "secret-token"
    assert seen[1].url.params["user_id"] == "9007199254740993"
    assert "secret-token" not in str(seen[1].url)
    assert json.loads(seen[1].content) == {"text": "Нет воды"}


@pytest.mark.asyncio
async def test_client_rejects_200_without_semantic_success() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/messages" and request.method == "PUT":
            return httpx.Response(200, json={"success": False, "message": "failed"})
        return httpx.Response(200, json={"success": False})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
    ) as http:
        api = MaxApiClient(http, "secret-token")
        with pytest.raises(MaxApiError):
            await api.edit_text("mid.abc", "Изменено")
        with pytest.raises(MaxApiError):
            await api.answer_callback("callback-1", "Голос учтён.")


@pytest.mark.asyncio
async def test_client_answers_callback_with_non_empty_notification() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
    ) as http:
        api = MaxApiClient(http, "secret-token")
        await api.answer_callback("callback-1", "Голос учтён.")
        with pytest.raises(ValueError):
            await api.answer_callback("callback-2", "  ")
    assert seen[0].url.params["callback_id"] == "callback-1"
    assert json.loads(seen[0].content) == {"notification": "Голос учтён."}


@pytest.mark.asyncio
async def test_client_sends_and_edits_inline_callback_keyboard() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "PUT":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"message": {"body": {"mid": "mid.poll"}}})

    keyboard: list[dict[str, object]] = [
        {
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [
                        {"type": "callback", "text": "За", "payload": "opaque-yes"},
                        {"type": "callback", "text": "Против", "payload": "opaque-no"},
                    ]
                ]
            },
        }
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
    ) as http:
        api = MaxApiClient(http, "secret-token")
        assert await api.send_text("Позиция", chat_id=123, attachments=keyboard) == "mid.poll"
        await api.edit_text("mid.poll", "Позиция обновлена", attachments=keyboard)
    assert [json.loads(request.content)["attachments"] for request in seen] == [keyboard, keyboard]


@pytest.mark.asyncio
async def test_client_requests_upload_slot_without_leaking_token_to_url() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"url": "https://uploads.example.invalid/slot", "token": "file-token"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
    ) as http:
        slot = await MaxApiClient(http, "secret-token").request_upload("file")
    assert slot.token == "file-token"
    assert seen[0].url.path == "/uploads"
    assert seen[0].url.params["type"] == "file"
    assert seen[0].headers["Authorization"] == "secret-token"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_client_reads_polling_batch_without_losing_large_ids() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "updates": [{"update_type": "unknown", "timestamp": 1}],
                "marker": 9_007_199_254_740_993,
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
    ) as http:
        batch = await MaxApiClient(http, "secret-token").get_updates(marker=42)

    assert batch.marker == 9_007_199_254_740_993
    assert len(batch.updates) == 1
    assert seen[0].url.params["marker"] == "42"


@pytest.mark.asyncio
async def test_client_reads_only_redacted_message_summary() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "sender": {"user_id": 123, "name": "Private sender"},
                "recipient": {"chat_id": -9007199254740993},
                "body": {
                    "mid": "mid_abc-123",
                    "text": "Private message text",
                    "attachments": [
                        {"type": "file", "payload": {"token": "private-token"}},
                        {"type": "inline_keyboard", "payload": {"buttons": []}},
                    ],
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
    ) as http:
        summary = await MaxApiClient(http, "secret-token").get_message_summary("mid.abc-123")

    assert summary.has_text is True
    assert summary.attachment_types == ("file", "inline_keyboard")
    assert seen[0].url.path == "/messages/mid.abc-123"
    assert seen[0].headers["Authorization"] == "secret-token"
    assert "Private" not in repr(summary)
    assert "private-token" not in repr(summary)


@pytest.mark.asyncio
async def test_client_rejects_unsafe_message_id_before_request() -> None:
    async with httpx.AsyncClient(base_url="https://platform-api2.max.ru") as http:
        api = MaxApiClient(http, "secret-token")
        with pytest.raises(ValueError, match="invalid MAX message ID"):
            await api.get_message_summary("../me")


@pytest.mark.asyncio
async def test_client_lists_and_deletes_webhook_subscription() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"subscriptions": [{"url": "https://bot.example/webhook/max"}]},
            )
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
    ) as http:
        api = MaxApiClient(http, "secret-token")
        assert len(await api.list_webhooks()) == 1
        await api.delete_webhook("https://bot.example/webhook/max")

    assert seen[1].method == "DELETE"
    assert seen[1].url.params["url"] == "https://bot.example/webhook/max"
