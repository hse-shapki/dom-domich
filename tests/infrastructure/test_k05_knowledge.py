"""Проверка K05 на мигрированной PostgreSQL через TEST_DATABASE_URL."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from dom_domych.agent.contracts import KnowledgeSearch, TrustedContext
from dom_domych.application.knowledge.service import KnowledgeService
from dom_domych.contracts.base import ExecutionMode, PrincipalType
from dom_domych.domain.knowledge.models import RuleVersion, SourceRevision
from dom_domych.infrastructure.postgres.knowledge import PostgresKnowledgeRepository
from dom_domych.infrastructure.postgres.knowledge_models import (
    KnowledgeChunkRow,
    KnowledgeSourceRow,
    RuleVersionRow,
)
from dom_domych.infrastructure.postgres.models import HouseRow
from dom_domych.infrastructure.postgres.session import database_lifespan


def _context(house_id: UUID) -> TrustedContext:
    return TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=house_id,
        actor_id=uuid4(),
        principal_type=PrincipalType.DEMO_OPERATOR,
        capabilities=frozenset({"knowledge.manage", "knowledge.read"}),
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )


@pytest.mark.asyncio
async def test_reviewed_knowledge_is_house_scoped_and_rule_is_explicit() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, other_house = uuid4(), uuid4()
    now = datetime.now(UTC)
    source_id = uuid4()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add_all(
                [
                    HouseRow(id=house_id, address="K05 дом 1", timezone="UTC", demo=True),
                    HouseRow(id=other_house, address="K05 дом 2", timezone="UTC", demo=True),
                ]
            )
        try:
            repository = PostgresKnowledgeRepository(sessions)
            service = KnowledgeService(repository, frozenset({"example.gov.ru"}))
            context = _context(house_id)
            source = SourceRevision(
                source_id=source_id,
                revision=1,
                house_id=house_id,
                title="Освещение",
                uri="https://example.gov.ru/rule/1",
                text="За освещение общей лестницы отвечает назначенная организация.",
                reviewed=False,
            )
            await service.ingest(source, context)
            query = KnowledgeSearch(query="освещение лестницы", topic="lighting")
            assert await service.search(query, context, at=now) == ()
            assert await service.review(source_id, 1, house_id, context)
            hits = await service.search(query, context, at=now)
            assert len(hits) == 1
            assert hits[0].source_id == source_id and hits[0].revision == 1
            assert await service.search(query, _context(other_house), at=now) == ()
            assert await service.applicable_rule("lighting", context, at=now) is None
            rule = RuleVersion(
                rule_id=uuid4(),
                source_id=source_id,
                source_revision=1,
                house_id=house_id,
                topic="lighting",
                responsible_id=uuid4(),
                deadline=timedelta(hours=4),
                deadline_origin="request.registered",
            )
            await service.add_rule(rule, context)
            assert await service.applicable_rule("lighting", context, at=now) == rule
            assert await service.applicable_rule("lighting", _context(other_house), at=now) is None
            with pytest.raises(PermissionError):
                await service.ingest(source, _context(other_house))
        finally:
            async with sessions.begin() as session:
                await session.execute(
                    delete(RuleVersionRow).where(RuleVersionRow.source_id == source_id)
                )
                await session.execute(
                    delete(KnowledgeChunkRow).where(KnowledgeChunkRow.source_id == source_id)
                )
                await session.execute(
                    delete(KnowledgeSourceRow).where(KnowledgeSourceRow.source_id == source_id)
                )
                await session.execute(
                    delete(HouseRow).where(HouseRow.id.in_([house_id, other_house]))
                )
