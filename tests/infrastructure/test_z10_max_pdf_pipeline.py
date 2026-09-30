"""Z10/Z15: четыре frozen PDF доходят до приватной MAX отправки."""

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import httpx
import pytest
from pypdf import PdfReader
from sqlalchemy import select, update

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.documents.worker import DocumentWorker
from dom_domych.application.notifications.worker import DeliveryWorker
from dom_domych.application.polls.service import PollService
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.documents.snapshot import DocumentKind
from dom_domych.domain.polls.models import PollKind
from dom_domych.domain.polls.policy import demo_initiative_policy
from dom_domych.infrastructure.documents.renderer import PdfRenderer
from dom_domych.infrastructure.files.local import LocalFileStore
from dom_domych.infrastructure.max.client import MaxApiClient
from dom_domych.infrastructure.max.media import MaxMediaTransport
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.documents import PostgresDocuments
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.models import HouseRow, OutboxDeliveryRow, ResidentRow
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_document_models import DocumentRow
from scripts.generate_zamira_demo_pdfs import sample_snapshots
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE


@dataclass(frozen=True)
class Context:
    house_id: UUID


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 14, tzinfo=UTC)


@pytest.mark.asyncio
async def test_all_four_documents_reach_private_max_file_delivery(tmp_path) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z10 requires a dedicated migrated PostgreSQL test database")
    clock = FixedClock()
    case_id = uuid4()
    recipient_id: UUID
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            address = await session.scalar(select(HouseRow.address).where(HouseRow.id == HOUSE_ONE))
            assert address is not None
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=HOUSE_ONE,
                    kind="initiative",
                    title="PDF pipeline",
                    description="Синтетический тест",
                    status="collecting",
                    version=1,
                    created_at=clock.now(),
                )
            )
            audience = await AudienceService(
                PostgresHouseContext(session, clock), PostgresAudienceRepository(session), clock
            ).resolve(
                AudienceScope(ScopeKind.FLOOR, entrance=2, floor=5),
                Context(HOUSE_ONE),
                operation_key=f"z10:audience:{case_id}",
            )
            poll = await PollService(PostgresPollRepository(session), clock).open(
                case_id,
                audience,
                PollKind.INITIATIVE_POSITION,
                demo_initiative_policy(),
                1,
                Context(HOUSE_ONE),
                operation_key=f"z10:poll:{case_id}",
                window=timedelta(days=2),
            )
            recipient_id = audience.members[0].resident_id
            await session.execute(
                update(ResidentRow).where(ResidentRow.id == recipient_id).values(max_user_id="222")
            )
        documents = PostgresDocuments(sessions)
        prepared = []
        for sample in sample_snapshots():
            snapshot = replace(
                sample,
                house_id=HOUSE_ONE,
                case_id=case_id,
                case_revision=1,
                audience_id=audience.audience_id,
                audience_revision=audience.criteria_revision,
                poll_id=poll.definition.poll_id,
                poll_revision=poll.version,
                policy_revision=poll.definition.policy.revision,
                request_id=None,
                request_revision=None,
                tally=poll.tally,
                house_address=address,
                created_at=clock.now(),
            )
            prepared.append(
                (
                    snapshot,
                    await documents.prepare(
                        snapshot,
                        recipient_id,
                        operation_key=f"z10:document:{case_id}:{snapshot.kind.value}",
                    ),
                )
            )
        async with sessions.begin() as session:
            await session.execute(
                update(OutboxDeliveryRow)
                .where(OutboxDeliveryRow.status == "pending")
                .values(status="sent")
            )
        files = LocalFileStore(tmp_path / "files", clock)
        async with PdfRenderer(max_workers=1) as renderer:
            worker = DocumentWorker(sessions, files, renderer, clock, "z10-four-pdfs")
            for _ in prepared:
                assert await worker.run_once() is True
            assert await worker.run_once() is False

        api_requests: list[httpx.Request] = []
        media_requests: list[httpx.Request] = []

        def api_response(request: httpx.Request) -> httpx.Response:
            api_requests.append(request)
            if request.url.path == "/uploads":
                return httpx.Response(200, json={"url": "https://fu.oneme.ru/upload.do"})
            return httpx.Response(200, json={"message": {"body": {"mid": str(uuid4())}}})

        def media_response(request: httpx.Request) -> httpx.Response:
            media_requests.append(request)
            return httpx.Response(200, json={"token": f"file-token-{len(media_requests)}"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(api_response), base_url="https://platform-api2.max.ru"
        ) as api_http:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(media_response)
            ) as media_http:
                api = MaxApiClient(api_http, "synthetic-token")
                worker = DeliveryWorker(
                    sessions,
                    api,
                    clock,
                    "z10-max-file-delivery",
                    media=MaxMediaTransport(media_http, api),
                    files=files,
                )
                for _ in prepared:
                    assert await worker.run_once() is True
                assert await worker.run_once() is False

        assert len(media_requests) == 4
        assert all("authorization" not in request.headers for request in media_requests)
        uploads = [request for request in api_requests if request.url.path == "/uploads"]
        messages = [request for request in api_requests if request.url.path == "/messages"]
        assert len(uploads) == len(messages) == 4
        assert all(request.url.params.get("user_id") == "222" for request in messages)
        assert all("chat_id" not in request.url.params for request in messages)
        assert {
            json.loads(request.content)["attachments"][0]["payload"]["token"]
            for request in messages
        } == {f"file-token-{index}" for index in range(1, 5)}
        for snapshot, ref in prepared:
            ready = await documents.get(ref.document_id, HOUSE_ONE)
            assert ready is not None and ready.status == "ready" and ready.file_key is not None
            stored, content = await files.get(HOUSE_ONE, ready.file_key)
            assert stored.sha256 == hashlib.sha256(content).hexdigest()
            pages = PdfReader(BytesIO(content)).pages
            assert len(pages) >= 1
            extracted = "\n".join(page.extract_text() for page in pages)
            assert snapshot.sha256 in extracted
            assert snapshot.template_revision in extracted
            assert "ТЕСТОВЫЕ ДАННЫЕ / ДЕМО" in extracted
            if snapshot.kind is not DocumentKind.NOTIFICATION_REGISTER:
                assert str(snapshot.notices[0].resident_id) not in extracted
            async with sessions() as session:
                row = await session.get(DocumentRow, ref.document_id)
                outbox = await session.scalar(
                    select(OutboxDeliveryRow).where(
                        OutboxDeliveryRow.operation_key == f"document:file:{ref.document_id}"
                    )
                )
                assert row is not None and row.snapshot_sha256 == snapshot.sha256
                assert row.file_sha256 == stored.sha256
                assert outbox is not None and outbox.status == "sent"
                assert outbox.recipient_id == recipient_id and outbox.chat_id is None
                assert outbox.file_key == ready.file_key and outbox.attachment_token is not None
        async with sessions.begin() as session:
            await session.execute(
                update(ResidentRow).where(ResidentRow.id == recipient_id).values(max_user_id=None)
            )
