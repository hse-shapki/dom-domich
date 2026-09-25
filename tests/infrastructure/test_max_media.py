"""A11: MAX PDF upload, attachment retry и безопасная загрузка фото."""

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, update

from dom_domych.application.notifications.worker import DeliveryWorker
from dom_domych.domain.ports.core import DeliveryIntent
from dom_domych.infrastructure.files.local import FileKind, LocalFileStore
from dom_domych.infrastructure.max.client import MaxApiClient
from dom_domych.infrastructure.max.evidence import EvidenceSourceDenied, MaxEvidenceLoader
from dom_domych.infrastructure.max.media import (
    MaxMediaError,
    MaxMediaTransport,
    extract_image_urls,
)
from dom_domych.infrastructure.max.updates import normalize_update
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.inbox import save_inbox_event
from dom_domych.infrastructure.postgres.models import (
    HouseRow,
    InboxEventRow,
    OutboxDeliveryRow,
    ResidentRow,
)
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO, synthetic_id


class FixedClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("A11 requires dedicated migrated PostgreSQL test database")
    return value


@pytest.mark.asyncio
async def test_media_rejects_external_hosts_and_downloads_bounded_image() -> None:
    seen: list[httpx.Request] = []

    def media_response(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, headers={"content-type": "image/png"}, content=b"\x89PNG\r\n\x1a\nabc"
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(media_response), timeout=5
    ) as media_http:
        async with httpx.AsyncClient(base_url="https://platform-api2.max.ru") as api_http:
            media = MaxMediaTransport(media_http, MaxApiClient(api_http, "secret"))
            with pytest.raises(MaxMediaError):
                await media.download_image("http://127.0.0.1/private")
            with pytest.raises(MaxMediaError):
                await media.download_image("https://oneme.ru.evil.test/private")
            with pytest.raises(MaxMediaError):
                await media.download_image("https://fu.oneme.ru:8443/private")
            mime, content = await media.download_image("https://cdn.oneme.ru/attached.png")
    assert mime == "image/png" and content.startswith(b"\x89PNG")
    assert len(seen) == 1 and "authorization" not in seen[0].headers
    assert extract_image_urls(
        {
            "message": {
                "body": {
                    "attachments": [
                        {"type": "image", "payload": {"url": "https://cdn.oneme.ru/attached.png"}},
                        {"type": "inline_keyboard", "payload": {"url": "https://evil.test"}},
                    ]
                }
            }
        }
    ) == ("https://cdn.oneme.ru/attached.png",)


@pytest.mark.asyncio
async def test_pdf_upload_token_is_reused_when_max_says_attachment_not_ready(tmp_path) -> None:
    clock = FixedClock()
    recipient_id = synthetic_id("resident-2")
    files = LocalFileStore(tmp_path / "files", clock)
    document = await files.put(HOUSE_ONE, FileKind.DOCUMENT, "application/pdf", b"%PDF-1.4\n%%EOF")
    api_seen: list[httpx.Request] = []
    media_seen: list[httpx.Request] = []
    sends = 0

    def api_response(request: httpx.Request) -> httpx.Response:
        nonlocal sends
        api_seen.append(request)
        if request.url.path == "/uploads":
            return httpx.Response(200, json={"url": "https://fu.oneme.ru/upload.do?sig=demo"})
        sends += 1
        if sends == 1:
            return httpx.Response(400, json={"code": "attachment.not.ready"})
        return httpx.Response(200, json={"message": {"body": {"mid": "pdf.1"}}})

    def media_response(request: httpx.Request) -> httpx.Response:
        media_seen.append(request)
        return httpx.Response(200, json={"token": "uploaded-file-token"})

    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(ResidentRow).where(ResidentRow.id == recipient_id).values(max_user_id="222")
            )
            delivery_id = await PostgresDeliveryQueue(session, clock).enqueue(
                DeliveryIntent(
                    HOUSE_ONE,
                    f"a11:{uuid4()}",
                    "Обращение",
                    recipient_id=recipient_id,
                    file_key=document.file_key,
                )
            )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(api_response), base_url="https://platform-api2.max.ru"
        ) as api_http:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(media_response)
            ) as media_http:
                api = MaxApiClient(api_http, "secret")
                media = MaxMediaTransport(media_http, api)
                worker = DeliveryWorker(
                    sessions, api, clock, "a11-worker", media=media, files=files
                )
                assert await worker.run_once()
                clock.current += timedelta(seconds=5)
                assert await worker.run_once()
        async with sessions.begin() as session:
            row = await session.get(OutboxDeliveryRow, delivery_id)
            assert row is not None and row.status == "sent"
            assert row.attachment_token == "uploaded-file-token"
            assert row.max_message_id == "pdf.1"
            await session.execute(
                delete(OutboxDeliveryRow).where(OutboxDeliveryRow.id == delivery_id)
            )
            await session.execute(
                update(ResidentRow).where(ResidentRow.id == recipient_id).values(max_user_id=None)
            )
    assert len(media_seen) == 1 and "authorization" not in media_seen[0].headers
    assert [request.url.path for request in api_seen] == ["/uploads", "/messages", "/messages"]
    for request in api_seen[1:]:
        assert json.loads(request.content)["attachments"] == [
            {"type": "file", "payload": {"token": "uploaded-file-token"}}
        ]


@pytest.mark.asyncio
async def test_evidence_loader_requires_house_chat_and_confirmed_author(tmp_path) -> None:
    clock = FixedClock()
    resident_id = synthetic_id("resident-2")
    raw: dict[str, object] = {
        "update_type": "message_created",
        "timestamp": int(clock.now().timestamp() * 1000),
        "message": {
            "sender": {"user_id": 222},
            "recipient": {"chat_id": 333},
            "timestamp": int(clock.now().timestamp() * 1000),
            "body": {
                "mid": f"evidence-{uuid4()}",
                "attachments": [
                    {"type": "image", "payload": {"url": "https://cdn.oneme.ru/photo.png"}}
                ],
            },
        },
    }
    source_key, event = normalize_update(raw, clock.now())
    assert event is not None
    media_requests: list[httpx.Request] = []

    def media_response(request: httpx.Request) -> httpx.Response:
        media_requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "image/png"}, content=b"\x89PNG\r\n\x1a\nabc"
        )

    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id="333")
            )
            await session.execute(
                update(ResidentRow).where(ResidentRow.id == resident_id).values(max_user_id="222")
            )
            await save_inbox_event(session, source_key, event, raw, clock.now())
        async with httpx.AsyncClient(transport=httpx.MockTransport(media_response)) as media_http:
            async with httpx.AsyncClient(base_url="https://platform-api2.max.ru") as api_http:
                media = MaxMediaTransport(media_http, MaxApiClient(api_http, "secret"))
                files = LocalFileStore(tmp_path / "evidence", clock)
                loader = MaxEvidenceLoader(sessions, media, files)
                with pytest.raises(EvidenceSourceDenied):
                    await loader.load_images(event.event_id, HOUSE_TWO)
                stored = await loader.load_images(event.event_id, HOUSE_ONE)
                assert len(stored) == 1 and stored[0].kind is FileKind.EVIDENCE
                assert (await files.get(HOUSE_ONE, stored[0].file_key))[1].startswith(b"\x89PNG")
        async with sessions.begin() as session:
            await session.execute(delete(InboxEventRow).where(InboxEventRow.id == event.event_id))
            await session.execute(
                update(ResidentRow).where(ResidentRow.id == resident_id).values(max_user_id=None)
            )
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id=None)
            )
    assert len(media_requests) == 1
