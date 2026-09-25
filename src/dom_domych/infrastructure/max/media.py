"""Безопасный транспорт файлов MAX: отдельный HTTP client без Bot API токена."""

from collections.abc import Iterable
from urllib.parse import urlsplit

import httpx

from dom_domych.infrastructure.max.client import MaxApiClient


class MaxMediaError(ValueError):
    pass


class MaxMediaHttpError(MaxMediaError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"MAX media transport HTTP {status_code}")
        self.status_code = status_code


class MaxMediaTransport:
    """Разрешённые CDN hosts задаются явно; redirects, auth и произвольные URL запрещены."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        max_api: MaxApiClient,
        *,
        allowed_domains: Iterable[str] = ("oneme.ru", "okcdn.ru"),
        max_size_bytes: int = 20_000_000,
    ) -> None:
        if client.auth is not None or "authorization" in client.headers:
            raise ValueError("media client must not carry Bot API credentials")
        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be positive")
        self.client = client
        self.max_api = max_api
        self.allowed_domains = frozenset(domain.lower() for domain in allowed_domains)
        self.max_size_bytes = max_size_bytes

    def _check_url(self, url: str) -> None:
        parsed = urlsplit(url)
        host = parsed.hostname
        try:
            port = parsed.port
        except ValueError as exc:
            raise MaxMediaError("invalid media port") from exc
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or not any(
                host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains
            )
        ):
            raise MaxMediaError("media URL outside configured MAX CDN hosts")

    async def upload_pdf(self, content: bytes, filename: str) -> str:
        if not content.startswith(b"%PDF-") or not 0 < len(content) <= self.max_size_bytes:
            raise MaxMediaError("PDF signature or size invalid")
        if not filename.endswith(".pdf") or "/" in filename or "\\" in filename:
            raise MaxMediaError("invalid PDF filename")
        slot = await self.max_api.request_upload("file")
        self._check_url(slot.url)
        response = await self.client.post(
            slot.url,
            files={"data": (filename, content, "application/pdf")},
            follow_redirects=False,
        )
        if response.status_code != 200:
            raise MaxMediaHttpError(response.status_code)
        if len(response.content) > 100_000:
            raise MaxMediaError("upload response too large")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            token = slot.token
        if not token:
            raise MaxMediaError("upload returned no attachment token")
        return token

    async def download_image(self, url: str) -> tuple[str, bytes]:
        self._check_url(url)
        async with self.client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code != 200:
                raise MaxMediaHttpError(response.status_code)
            mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                raise MaxMediaError("unsupported evidence MIME")
            size_header = response.headers.get("content-length")
            if size_header and size_header.isdecimal() and int(size_header) > self.max_size_bytes:
                raise MaxMediaError("evidence too large")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self.max_size_bytes:
                    raise MaxMediaError("evidence too large")
                chunks.append(chunk)
        return mime, b"".join(chunks)


def extract_image_urls(raw_update: dict[str, object]) -> tuple[str, ...]:
    """URL берётся только из MAX attachment payload, не из текста сообщения."""

    message = raw_update.get("message")
    if not isinstance(message, dict):
        return ()
    body = message.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("attachments"), list):
        return ()
    urls: list[str] = []
    for item in body["attachments"]:
        if not isinstance(item, dict) or item.get("type") != "image":
            continue
        payload = item.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("url"), str):
            urls.append(payload["url"])
    return tuple(urls)
