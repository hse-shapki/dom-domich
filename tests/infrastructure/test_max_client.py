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
            await api.answer_callback("callback-1")


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
