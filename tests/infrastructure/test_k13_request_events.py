"""K13: trusted Z events mutate K state before agent continuation."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.application.requests.events import RequestEventHandler
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.ports.core import DocumentRef, RequestRef
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseRow
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import HouseRow
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.requests import PostgresRequestStore
from dom_domych.infrastructure.postgres.session import database_lifespan

NOW = datetime(2026, 9, 26, 14, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeExecutor:
    def __init__(self, value: RequestRef) -> None:
        self.value = value

    async def get_status(self, request_id: UUID, house_id: UUID) -> RequestRef:
        assert request_id == self.value.request_id and house_id == self.value.house_id
        return self.value


class FakeDocuments:
    def __init__(self, value: DocumentRef) -> None:
        self.value = value

    async def get(self, document_id: UUID, house_id: UUID) -> DocumentRef | None:
        if document_id != self.value.document_id or house_id != self.value.house_id:
            return None
        return self.value


class FailingStore:
    async def record_external_status(self, event: EventEnvelope, external: RequestRef) -> object:
        raise AssertionError("untrusted event reached store")

    async def bind_document(self, event: EventEnvelope, document: DocumentRef) -> object:
        raise AssertionError("untrusted event reached store")


def _event(
    name: EventName,
    source: EventSource,
    house_id: UUID,
    entity_id: UUID,
    version: int,
    case_id: UUID,
) -> EventEnvelope:
    event_id = uuid4()
    return EventEnvelope(
        event_id=event_id,
        source=source,
        source_key=f"k13:{event_id}",
        name=name,
        occurred_at=NOW,
        received_at=NOW,
        correlation_id=uuid4(),
        house_id=house_id,
        entity=EntityEventPayload(
            entity_id=entity_id,
            entity_version=version,
            case_id=case_id,
        ),
    )


@pytest.mark.asyncio
async def test_status_and_document_are_committed_before_continuation() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, case_id, request_id, document_id, file_key = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    source_id, rule_id, responsible_id = uuid4(), uuid4(), uuid4()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add(HouseRow(id=house_id, address="K13 дом", timezone="UTC", demo=True))
            await session.flush()
            session.add(
                KnowledgeSourceRow(
                    source_id=source_id,
                    revision=1,
                    house_id=house_id,
                    title="DEMO правило",
                    uri="https://example.test/k13",
                    text="Тестовый источник",
                    reviewed=True,
                    valid_from=None,
                    valid_until=None,
                )
            )
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=house_id,
                    kind="problem",
                    title="Нет света",
                    description="Нет света на этаже",
                    entrance=1,
                    floor=2,
                    object_name="lighting",
                    status="in_progress",
                    version=4,
                    created_at=NOW,
                    closed_at=None,
                    recurrence_of=None,
                    embedding=None,
                    embedding_revision=None,
                )
            )
        async with sessions.begin() as session:
            session.add(
                RuleVersionRow(
                    id=rule_id,
                    source_id=source_id,
                    source_revision=1,
                    house_id=house_id,
                    topic="lighting",
                    responsible_id=responsible_id,
                    duration_seconds=None,
                    deadline_origin=None,
                    valid_from=None,
                    valid_until=None,
                )
            )
            session.add(
                RequestRow(
                    id=request_id,
                    house_id=house_id,
                    case_id=case_id,
                    draft_id=uuid4(),
                    draft_version=1,
                    content_sha256="a" * 64,
                    responsible_id=responsible_id,
                    rule_id=rule_id,
                    source_refs=[f"{source_id}:1"],
                    status="registered",
                    approved_version=1,
                    approval_actor=None,
                    submit_operation_id=uuid4(),
                    executor_operation_id=uuid4(),
                    registration_id="DEMO-K13",
                    registered_at=NOW,
                    external_status="registered",
                    external_version=1,
                    external_status_updated_at=NOW,
                    document_id=None,
                    document_snapshot_hash=None,
                    document_file_key=None,
                )
            )
        try:
            status_ref = RequestRef(request_id, case_id, house_id, 2, "in_progress")
            document_ref = DocumentRef(document_id, house_id, case_id, "ready", file_key, "b" * 64)
            handler = RequestEventHandler(
                FakeExecutor(status_ref),
                FakeDocuments(document_ref),
                PostgresRequestStore(sessions, FixedClock()),
            )
            seen_versions: list[int] = []

            async def continuation(_event: EventEnvelope) -> bool:
                async with sessions() as session:
                    case = await session.get(CaseRow, case_id)
                    assert case is not None
                    seen_versions.append(case.version)
                return True

            status_event = _event(
                EventName.REQUEST_STATUS_CHANGED,
                EventSource.EXECUTOR,
                house_id,
                request_id,
                2,
                case_id,
            )
            dispatcher = EventDispatcher(
                {EventName.REQUEST_STATUS_CHANGED: [handler, continuation]}
            )
            await dispatcher.handle(status_event)
            await dispatcher.handle(status_event)
            document_event = _event(
                EventName.DOCUMENT_READY,
                EventSource.DOMAIN,
                house_id,
                document_id,
                1,
                case_id,
            )
            await EventDispatcher({EventName.DOCUMENT_READY: [handler, continuation]}).handle(
                document_event
            )

            async with sessions() as session:
                request = await session.get(RequestRow, request_id)
                case = await session.get(CaseRow, case_id)
                assert request is not None and case is not None
                assert request.external_status == "in_progress"
                assert request.external_version == 2
                assert request.document_id == document_id
                assert request.document_snapshot_hash == "b" * 64
                assert request.document_file_key == file_key
                assert case.status == "in_progress" and case.version == 6
            assert seen_versions == [5, 5, 6]
        finally:
            async with sessions.begin() as session:
                await session.execute(delete(CaseEventRow).where(CaseEventRow.case_id == case_id))
                await session.execute(delete(RequestRow).where(RequestRow.id == request_id))
                await session.execute(delete(CaseRow).where(CaseRow.id == case_id))
                await session.execute(delete(RuleVersionRow).where(RuleVersionRow.id == rule_id))
                await session.execute(
                    delete(KnowledgeSourceRow).where(KnowledgeSourceRow.source_id == source_id)
                )
                await session.execute(delete(HouseRow).where(HouseRow.id == house_id))


@pytest.mark.asyncio
async def test_request_event_handler_rejects_untrusted_source() -> None:
    house_id, case_id, request_id = uuid4(), uuid4(), uuid4()
    handler = RequestEventHandler(
        FakeExecutor(RequestRef(request_id, case_id, house_id, 2, "done")),
        FakeDocuments(DocumentRef(uuid4(), house_id, case_id, "ready", uuid4(), "a" * 64)),
        FailingStore(),
    )
    event = _event(
        EventName.REQUEST_STATUS_CHANGED,
        EventSource.MAX,
        house_id,
        request_id,
        2,
        case_id,
    )

    with pytest.raises(ValueError, match="UNTRUSTED_REQUEST_STATUS_EVENT"):
        await handler(event)
