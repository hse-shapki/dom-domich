"""Команды MAX: доверенный житель, приватное фото, проверенное правило и demo submit."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from dom_domych.application.agent.resident_actions import ResidentAction, parse_resident_action
from dom_domych.application.agent.resident_production import PostgresResidentActions
from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.initiatives.service import InitiativeService
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource, MessagePayload
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.polls.policy import demo_initiative_policy
from dom_domych.infrastructure.files.local import FileKind, LocalFileStore
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseEvidenceRow, CaseMessageRow, CaseRow
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.initiative_cases import PostgresInitiativeCases
from dom_domych.infrastructure.postgres.initiatives import PostgresInitiativeRepository
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import HouseRow, ResidentRow
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class FakeLoader:
    def __init__(self, files: LocalFileStore) -> None:
        self.files = files
        self.calls = 0

    async def load_images(self, event_id: UUID, house_id: UUID):
        self.calls += 1
        return (
            await self.files.put(
                house_id, FileKind.EVIDENCE, "image/png", b"\x89PNG\r\n\x1a\nphoto"
            ),
        )


def _context(house_id: UUID, actor_id: UUID, event_id: UUID) -> TrustedContext:
    return TrustedContext(
        run_id=uuid4(),
        event_id=event_id,
        house_id=house_id,
        actor_id=actor_id,
        principal_type=PrincipalType.RESIDENT,
        capabilities=frozenset(),
        correlation_id=event_id,
        mode=ExecutionMode.DEMO,
    )


def _event(event_id: UUID, text: str, *, image: bool = False) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        source=EventSource.MAX,
        source_key=f"message:{event_id}",
        name=EventName.MESSAGE_RECEIVED,
        occurred_at=NOW,
        received_at=NOW,
        correlation_id=event_id,
        actor_user_id="resident",
        message=MessagePayload(
            chat_id="dm:resident",
            message_id=str(event_id),
            sender_user_id="resident",
            text=text,
            attachment_refs=("image",) if image else (),
        ),
    )


def test_exact_resident_command_parser() -> None:
    case_id, evidence_id = uuid4(), uuid4()
    assert parse_resident_action("/confirm") == ResidentAction("confirm", None)
    assert parse_resident_action("Да") == ResidentAction("confirm", None)
    assert parse_resident_action(f"/revise {case_id} 1 Новая версия текста") == ResidentAction(
        "revise", case_id, 1, "Новая версия текста"
    )
    assert parse_resident_action(f"/assess {case_id} {evidence_id} accepted") == ResidentAction(
        "assess", case_id, evidence_id=evidence_id, assessment="accepted"
    )
    assert parse_resident_action("/sendx anything") is None
    with pytest.raises(ValueError, match="INVALID_ACTION"):
        parse_resident_action(f"/assess {case_id} {evidence_id} maybe")


@pytest.mark.asyncio
async def test_photo_assessment_and_request_need_author_and_reviewed_rule(tmp_path: Path) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, author_id, stranger_id, case_id = uuid4(), uuid4(), uuid4(), uuid4()
    source_id, rule_id, responsible_id = uuid4(), uuid4(), uuid4()
    files = LocalFileStore(tmp_path, Clock())
    loader = FakeLoader(files)
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add(HouseRow(id=house_id, address="Z MVP 1", timezone="UTC", demo=True))
            session.add_all(
                [
                    ResidentRow(id=author_id, display_name="Автор", active_house_id=house_id),
                    ResidentRow(id=stranger_id, display_name="Чужой", active_house_id=house_id),
                ]
            )
            await session.flush()
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=house_id,
                    kind="problem",
                    title="Не горит свет",
                    description="На лестнице погасла лампа",
                    entrance=1,
                    floor=2,
                    object_name="lighting",
                    status="request_ready",
                    version=1,
                    created_at=NOW,
                    closed_at=None,
                    recurrence_of=None,
                    embedding=None,
                    embedding_revision=None,
                )
            )
            await session.flush()
            session.add(
                CaseMessageRow(
                    case_id=case_id,
                    house_id=house_id,
                    message_id=uuid4(),
                    actor_id=author_id,
                    relation="origin",
                    linked_at=NOW,
                )
            )
        actions = PostgresResidentActions(sessions, Clock(), loader, files)  # type: ignore[arg-type]
        photo_event_id = uuid4()
        photo_event = _event(photo_event_id, f"/evidence {case_id}", image=True)
        author = _context(house_id, author_id, photo_event_id)
        reply = await actions.execute(ResidentAction("evidence", case_id), photo_event, author)
        assert "без анализа изображения" in reply
        assert loader.calls == 1
        repeated_reply = await actions.execute(
            ResidentAction("evidence", case_id), photo_event, author
        )
        assert repeated_reply == reply
        assert loader.calls == 1
        async with sessions() as session:
            evidence = await session.scalar(
                select(CaseEvidenceRow).where(CaseEvidenceRow.case_id == case_id)
            )
            assert evidence is not None and evidence.assessment == "pending"
            evidence_id = evidence.id
        assessment_id = uuid4()
        assessment = ResidentAction(
            "assess", case_id, evidence_id=evidence_id, assessment="accepted"
        )
        with pytest.raises(PermissionError):
            await actions.execute(
                assessment,
                _event(assessment_id, f"/assess {case_id} {evidence_id} accepted"),
                _context(house_id, stranger_id, assessment_id),
            )
        assessed = await actions.execute(
            assessment,
            _event(assessment_id, f"/assess {case_id} {evidence_id} accepted"),
            _context(house_id, author_id, assessment_id),
        )
        assert "не автоматическая проверка" in assessed
        assert "уже сохранена" in await actions.execute(
            assessment,
            _event(assessment_id, f"/assess {case_id} {evidence_id} accepted"),
            _context(house_id, author_id, assessment_id),
        )
        async with sessions() as session:
            evidence = await session.get(CaseEvidenceRow, evidence_id)
            assert evidence is not None and evidence.assessment == "accepted"
            assert evidence.file_key is not None
            await files.get(house_id, UUID(evidence.file_key))
        prepare_id = uuid4()
        prepare = ResidentAction("prepare", case_id)
        with pytest.raises(PermissionError):
            await actions.execute(
                prepare,
                _event(prepare_id, f"/prepare {case_id}"),
                _context(house_id, stranger_id, prepare_id),
            )
        assert "Обращение не подготовлено" in await actions.execute(
            prepare,
            _event(prepare_id, f"/prepare {case_id}"),
            _context(house_id, author_id, prepare_id),
        )
        async with sessions.begin() as session:
            session.add(
                KnowledgeSourceRow(
                    source_id=source_id,
                    revision=1,
                    house_id=house_id,
                    title="Правило",
                    uri="https://example.gov.ru/rule",
                    text="Ответственный назначен",
                    reviewed=True,
                    valid_from=None,
                    valid_until=None,
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
        prepare_id = uuid4()
        prepared = await actions.execute(
            prepare,
            _event(prepare_id, f"/prepare {case_id}"),
            _context(house_id, author_id, prepare_id),
        )
        assert "Проверенный источник" in prepared and str(responsible_id) in prepared
        async with sessions() as session:
            request = await session.scalar(select(RequestRow).where(RequestRow.case_id == case_id))
            assert request is not None and request.status == "prepared"
            request_id = request.id
        approve_id = uuid4()
        await actions.execute(
            ResidentAction("approve", request_id),
            _event(approve_id, f"/approve {request_id}"),
            _context(house_id, author_id, approve_id),
        )
        send_id = uuid4()
        with pytest.raises(PermissionError):
            await actions.execute(
                ResidentAction("send", request_id),
                _event(send_id, f"/send {request_id}"),
                _context(house_id, stranger_id, send_id),
            )
        sent = await actions.execute(
            ResidentAction("send", request_id),
            _event(send_id, f"/send {request_id}"),
            _context(house_id, author_id, send_id),
        )
        assert "тестовому исполнителю" in sent
        assert (
            await actions.execute(
                ResidentAction("send", request_id),
                _event(send_id, f"/send {request_id}"),
                _context(house_id, author_id, send_id),
            )
            == sent
        )


@pytest.mark.asyncio
async def test_author_revision_from_chat_replaces_poll_once(tmp_path: Path) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    case_id, author_id = uuid4(), synthetic_id("resident-2")
    files = LocalFileStore(tmp_path, Clock())
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=HOUSE_ONE,
                    kind="initiative",
                    title="Велопарковка",
                    description="Нужна новая парковка",
                    status="collecting",
                    version=1,
                    created_at=NOW,
                )
            )
            await session.flush()
            session.add(
                CaseMessageRow(
                    case_id=case_id,
                    house_id=HOUSE_ONE,
                    message_id=uuid4(),
                    actor_id=author_id,
                    relation="origin",
                    linked_at=NOW,
                )
            )
            audience = await AudienceService(
                PostgresHouseContext(session, Clock()),
                PostgresAudienceRepository(session),
                Clock(),
            ).resolve(
                AudienceScope(ScopeKind.FLOOR, entrance=2, floor=5),
                _context(HOUSE_ONE, author_id, uuid4()),
                operation_key=f"z-mvp1:audience:{case_id}",
            )
        service = InitiativeService(
            PostgresInitiativeCases(sessions), PostgresInitiativeRepository(sessions), Clock()
        )
        original = await service.create(
            case_id,
            "Велопарковка у второго подъезда",
            audience,
            demo_initiative_policy(),
            timedelta(days=2),
            _context(HOUSE_ONE, author_id, uuid4()),
            operation_key=f"z-mvp1:create:{case_id}",
        )
        actions = PostgresResidentActions(sessions, Clock(), FakeLoader(files), files)  # type: ignore[arg-type]
        action = ResidentAction("revise", case_id, 1, "Велопарковка на шесть мест")
        event_id = uuid4()
        event = _event(event_id, f"/revise {case_id} 1 Велопарковка на шесть мест")
        with pytest.raises(PermissionError):
            await actions.execute(action, event, _context(HOUSE_ONE, uuid4(), event_id))
        reply = await actions.execute(action, event, _context(HOUSE_ONE, author_id, event_id))
        assert "редакция 2" in reply
        assert "редакция 2" in await actions.execute(
            action, event, _context(HOUSE_ONE, author_id, event_id)
        )
        revised = await PostgresInitiativeRepository(sessions).get(case_id, HOUSE_ONE)
        assert revised.current.poll_id != original.current.poll_id
        assert revised.current.wording == "Велопарковка на шесть мест"
