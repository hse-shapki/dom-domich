"""Документированные методы Bot API; клиент создаётся на lifespan процесса."""

from dataclasses import dataclass
from typing import Literal

import httpx

MAX_API_BASE_URL = "https://platform-api2.max.ru"


class MaxApiError(Exception):
    def __init__(self, operation: str, status_code: int, code: str | None = None) -> None:
        super().__init__(f"MAX {operation} failed: HTTP {status_code}, code={code or 'unknown'}")
        self.operation = operation
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class BotIdentity:
    user_id: int
    username: str | None


@dataclass(frozen=True, slots=True)
class UploadSlot:
    url: str
    token: str | None


class MaxApiClient:
    """HTTPX session с timeout/TLS клиента; токен только в Bot API headers."""

    def __init__(self, client: httpx.AsyncClient, access_token: str) -> None:
        if not access_token:
            raise ValueError("MAX access token is required")
        self.client = client
        self._access_token = access_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, int | str] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        response = await self.client.request(
            method,
            path,
            params=params,
            json=body,
            headers={"Authorization": self._access_token},
            follow_redirects=False,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MaxApiError(path, response.status_code, "invalid_json") from exc
        if not isinstance(payload, dict):
            raise MaxApiError(path, response.status_code, "invalid_shape")
        code_value = payload.get("code")
        code = code_value if isinstance(code_value, str) else None
        if response.is_error or payload.get("success") is False or code is not None:
            raise MaxApiError(path, response.status_code, code)
        return payload

    async def get_me(self) -> BotIdentity:
        payload = await self._request("GET", "/me")
        user_id = payload.get("user_id")
        if type(user_id) is not int or payload.get("is_bot") is not True:
            raise MaxApiError("/me", 200, "invalid_bot_identity")
        username = payload.get("username")
        return BotIdentity(user_id, username if isinstance(username, str) else None)

    async def send_text(
        self,
        text: str,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        attachments: list[dict[str, object]] | None = None,
    ) -> str:
        if (user_id is None) == (chat_id is None):
            raise ValueError("exactly one recipient is required")
        if not text and not attachments:
            raise ValueError("message needs text or attachment")
        if user_id is not None:
            params: dict[str, int | str] = {"user_id": user_id}
        else:
            assert chat_id is not None
            params = {"chat_id": chat_id}
        body: dict[str, object] = {"text": text}
        if attachments is not None:
            body["attachments"] = attachments
        payload = await self._request("POST", "/messages", params=params, body=body)
        message = payload.get("message")
        if not isinstance(message, dict):
            raise MaxApiError("/messages", 200, "missing_message")
        content = message.get("body")
        if not isinstance(content, dict) or not isinstance(content.get("mid"), str):
            raise MaxApiError("/messages", 200, "missing_message_id")
        return content["mid"]

    async def edit_text(self, message_id: str, text: str) -> None:
        payload = await self._request(
            "PUT", "/messages", params={"message_id": message_id}, body={"text": text}
        )
        if payload.get("success") is not True:
            raise MaxApiError("/messages", 200, "missing_success")

    async def answer_callback(self, callback_id: str) -> None:
        payload = await self._request(
            "POST", "/answers", params={"callback_id": callback_id}, body={}
        )
        if payload.get("success") is not True:
            raise MaxApiError("/answers", 200, "missing_success")

    async def request_upload(self, kind: Literal["image", "file", "audio", "video"]) -> UploadSlot:
        payload = await self._request("POST", "/uploads", params={"type": kind})
        url = payload.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise MaxApiError("/uploads", 200, "invalid_upload_url")
        token = payload.get("token")
        return UploadSlot(url, token if isinstance(token, str) else None)

    async def register_webhook(self, url: str, secret: str, update_types: tuple[str, ...]) -> None:
        if not url.startswith("https://"):
            raise ValueError("webhook needs HTTPS")
        payload = await self._request(
            "POST",
            "/subscriptions",
            body={"url": url, "secret": secret, "update_types": list(update_types)},
        )
        if payload.get("success") is not True:
            raise MaxApiError("/subscriptions", 200, "missing_success")
