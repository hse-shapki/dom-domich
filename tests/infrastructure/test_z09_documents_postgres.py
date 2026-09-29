"""Z09: immutable snapshot и house-scoped метаданные документа."""

import asyncio
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.documents.worker import DocumentWorker
from dom_domych.application.jobs.inbox_worker import SystemClock
from dom_domych.application.polls.service import PollService
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.documents.snapshot import (
    DocumentFact,
    DocumentKind,
    DocumentMode,
    DocumentSnapshot,
)
from dom_domych.domain.polls.models import PollKind, VoteChoice
from dom_domych.domain.polls.policy import demo_initiative_policy
from dom_domych.infrastructure.documents.renderer import PdfRenderer, RenderedDocument
from dom_domych.infrastructure.files.local import LocalFileStore
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.documents import PostgresDocuments, verify_snapshot_bytes
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.models import OutboxDeliveryRow
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_document_models import DocumentRow
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO


@dataclass(frozen=True)
class Context:
    house_id: UUID


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_document_snapshot_is_idempotent_scoped_and_frozen(tmp_path: Path) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z09 requires a dedicated migrated PostgreSQL test database")
    clock = FixedClock()
    case_id = uuid4()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=HOUSE_ONE,
                    kind="initiative",
                    title="Велопарковка",
                    description="Тест",
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
                operation_key=f"z09:audience:{case_id}",
            )
            poll = await PollService(PostgresPollRepository(session), clock).open(
                case_id,
                audience,
                PollKind.INITIATIVE_POSITION,
                demo_initiative_policy(),
                1,
                Context(HOUSE_ONE),
                operation_key=f"z09:poll:{case_id}",
                window=timedelta(days=2),
            )
        snapshot = DocumentSnapshot(
            kind=DocumentKind.RESIDENT_POSITION,
            mode=DocumentMode.DEMO,
            template_revision="resident-position-v1",
            house_id=HOUSE_ONE,
            case_id=case_id,
            case_revision=1,
            audience_id=audience.audience_id,
            audience_revision=1,
            poll_id=poll.definition.poll_id,
            poll_revision=1,
            policy_revision=poll.definition.policy.revision,
            request_id=None,
            request_revision=None,
            title="Позиция по велопарковке",
            house_address="Демо: Москва, Тестовая улица, дом 1",
            facts=(DocumentFact("proposal", "Установить велопарковку", f"case:{case_id}"),),
            tally=poll.tally,
            notices=(),
            created_at=clock.now(),
        )
        documents = PostgresDocuments(sessions)
        recipient_id = audience.members[0].resident_id
        prepared = await documents.prepare(
            snapshot, recipient_id, operation_key=f"z09:document:{case_id}"
        )
        assert prepared.status == "queued" and prepared.file_key is None
        assert prepared.snapshot_hash == snapshot.sha256
        assert (
            await documents.prepare(snapshot, recipient_id, operation_key=f"z09:document:{case_id}")
            == prepared
        )
        assert await documents.get(prepared.document_id, HOUSE_TWO) is None
        async with sessions() as session:
            row = await session.get(DocumentRow, prepared.document_id)
            assert row is not None
            assert verify_snapshot_bytes(row) == snapshot
        with pytest.raises(ValueError, match="operation key conflicts"):
            await documents.prepare(
                replace(snapshot, title="Подменённое название"),
                recipient_id,
                operation_key=f"z09:document:{case_id}",
            )
        async with sessions.begin() as session:
            await PostgresPollRepository(session).record_answer_atomic(
                poll.definition.poll_id,
                HOUSE_ONE,
                recipient_id,
                VoteChoice.YES,
                uuid4(),
                clock.now() + timedelta(minutes=1),
            )
        with pytest.raises(ValueError, match="current poll"):
            await documents.prepare(snapshot, recipient_id, operation_key=f"z09:stale:{case_id}")
        assert (
            await documents.prepare(snapshot, recipient_id, operation_key=f"z09:document:{case_id}")
            == prepared
        )
        assert await documents.get(prepared.document_id, HOUSE_ONE) == prepared
        async with sessions.begin() as session:
            row = await session.get(DocumentRow, prepared.document_id)
            assert row is not None
            row.status = "rendering"
            row.lease_owner = "crashed-worker"
            row.lease_until = clock.now() - timedelta(seconds=1)
            row.attempts = 1
        files = LocalFileStore(tmp_path, clock)
        async with PdfRenderer(max_workers=1) as renderer:
            started = asyncio.Event()

            class SlowRenderer:
                async def render(self, frozen: DocumentSnapshot) -> RenderedDocument:
                    started.set()
                    await asyncio.sleep(0.4)
                    return await renderer.render(frozen)

            live_clock = SystemClock()
            worker = DocumentWorker(
                sessions,
                files,
                SlowRenderer(),
                live_clock,
                "z10-test",
                lease_for=timedelta(milliseconds=150),
            )
            rendering = asyncio.create_task(worker.run_once())
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                await asyncio.sleep(0.25)
                competitor = DocumentWorker(sessions, files, renderer, live_clock, "z10-competitor")
                assert not await competitor.run_once()
                assert await rendering
            finally:
                if not rendering.done():
                    rendering.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await rendering
            async with sessions() as session:
                row = await session.get(DocumentRow, prepared.document_id)
                assert row is not None and row.status == "ready", row.error_code if row else None
            assert await worker.run_once() is False
        ready = await documents.get(prepared.document_id, HOUSE_ONE)
        assert ready is not None and ready.status == "ready" and ready.file_key is not None
        stored, content = await files.get(HOUSE_ONE, ready.file_key)
        assert content.startswith(b"%PDF-")
        assert stored.sha256
        async with sessions() as session:
            row = await session.get(DocumentRow, ready.document_id)
            assert row is not None
            assert row.file_sha256 == stored.sha256 and row.attempts == 2
            outbox = await session.scalar(
                select(OutboxDeliveryRow).where(
                    OutboxDeliveryRow.house_id == HOUSE_ONE,
                    OutboxDeliveryRow.operation_key == f"document:file:{ready.document_id}",
                )
            )
            assert outbox is not None
            assert outbox.recipient_id == recipient_id and outbox.file_key == ready.file_key
        corrupt_id = uuid4()
        async with sessions.begin() as session:
            session.add(
                DocumentRow(
                    id=corrupt_id,
                    house_id=HOUSE_ONE,
                    case_id=case_id,
                    audience_id=audience.audience_id,
                    poll_id=poll.definition.poll_id,
                    recipient_id=recipient_id,
                    operation_key=f"z10:corrupt:{corrupt_id}",
                    kind=snapshot.kind.value,
                    mode=snapshot.mode.value,
                    template_revision=snapshot.template_revision,
                    snapshot_bytes=b"corrupt",
                    snapshot_sha256=snapshot.sha256,
                    status="queued",
                    created_at=clock.now(),
                    attempts=0,
                )
            )
        async with PdfRenderer(max_workers=1) as renderer:
            worker = DocumentWorker(sessions, files, renderer, clock, "z10-corrupt", max_attempts=2)
            assert await worker.run_once() is True
            assert await worker.run_once() is True
            assert await worker.run_once() is False
        async with sessions() as session:
            row = await session.get(DocumentRow, corrupt_id)
            assert row is not None and row.status == "failed" and row.attempts == 2
            assert row.file_key is None and row.error_code == "ValueError"

        # Crash на последней попытке не даёт бесконечно перезахватывать PDF.
        async with sessions.begin() as session:
            row = await session.get(DocumentRow, corrupt_id)
            assert row is not None
            row.status = "rendering"
            row.lease_owner = "last-crashed-worker"
            row.lease_until = clock.now() - timedelta(seconds=1)
        async with PdfRenderer(max_workers=1) as renderer:
            worker = DocumentWorker(
                sessions, files, renderer, clock, "z10-exhausted", max_attempts=2
            )
            assert await worker.run_once()
            assert not await worker.run_once()
        async with sessions() as session:
            row = await session.get(DocumentRow, corrupt_id)
            assert row is not None and row.status == "failed" and row.attempts == 2
            assert row.error_code == "render_attempts_exhausted" and row.file_key is None
