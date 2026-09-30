"""Z16: operator CLI ведёт demo executor через сервис, без ручного SQL."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.domain.executor.models import ApprovedDraft
from dom_domych.entrypoints.zamira_operator import build_parser, run_command
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.demo_executor import PostgresDemoExecutor
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import HouseRow, ResidencyRow
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO


@dataclass(frozen=True)
class Context:
    house_id: UUID
    capabilities: frozenset[str]


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 14, tzinfo=UTC)


@pytest.mark.asyncio
async def test_operator_cli_registers_replays_done_and_rejects_live_house() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in database_url:
        pytest.skip("Z16 CLI requires a dedicated migrated PostgreSQL test database")
    case_id, request_id, draft_id, rule_id, source_id = (uuid4() for _ in range(5))
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            approval_actor = await session.scalar(
                select(ResidencyRow.resident_id).where(ResidencyRow.house_id == HOUSE_ONE).limit(1)
            )
            assert approval_actor is not None
            session.add_all(
                [
                    CaseRow(
                        id=case_id,
                        house_id=HOUSE_ONE,
                        kind="problem",
                        title="CLI demo",
                        description="Синтетический тест",
                        status="preparing_request",
                        version=1,
                        created_at=Clock().now(),
                    ),
                    KnowledgeSourceRow(
                        source_id=source_id,
                        revision=1,
                        house_id=HOUSE_ONE,
                        title="Синтетическое правило",
                        uri="https://example.invalid/z16-cli",
                        text="Демо",
                        reviewed=True,
                    ),
                    RuleVersionRow(
                        id=rule_id,
                        source_id=source_id,
                        source_revision=1,
                        house_id=HOUSE_ONE,
                        topic="maintenance",
                        responsible_id=uuid4(),
                    ),
                ]
            )
            await session.flush()
            session.add(
                RequestRow(
                    id=request_id,
                    house_id=HOUSE_ONE,
                    case_id=case_id,
                    draft_id=draft_id,
                    draft_version=1,
                    content_sha256="a" * 64,
                    responsible_id=uuid4(),
                    rule_id=rule_id,
                    source_refs=["demo:1"],
                    status="submitting",
                    approved_version=1,
                    approval_actor=approval_actor,
                    external_version=0,
                )
            )
        operation = await DemoExecutorService(
            PostgresDemoExecutor(sessions, Clock()), Clock()
        ).submit(
            ApprovedDraft(HOUSE_ONE, request_id, draft_id, 1, "a" * 64),
            f"z16:submit:{request_id}",
            Context(HOUSE_ONE, frozenset({"demo_executor.submit"})),
        )
        event_id = uuid4()
        parser = build_parser()
        listed = await run_command(
            parser.parse_args(["list", "--house-id", str(HOUSE_ONE)]), database_url
        )
        assert str(operation.operation_id) in listed and "status=submitted" in listed
        register_args = parser.parse_args(
            [
                "register",
                "--house-id",
                str(HOUSE_ONE),
                "--operation-id",
                str(operation.operation_id),
            ]
        )
        first = await run_command(register_args, database_url)
        assert "status=registered" in first and "emitted=True" in first
        assert "emitted=False" in await run_command(register_args, database_url)
        done_args = parser.parse_args(
            [
                "done",
                "--house-id",
                str(HOUSE_ONE),
                "--operation-id",
                str(operation.operation_id),
                "--event-id",
                str(event_id),
            ]
        )
        assert "status=done" in await run_command(done_args, database_url)
        assert "emitted=False" in await run_command(done_args, database_url)
        async with sessions.begin() as session:
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_TWO).values(demo=False)
            )
        with pytest.raises(ValueError, match="only for an existing demo house"):
            await run_command(
                parser.parse_args(["list", "--house-id", str(HOUSE_TWO)]), database_url
            )
        async with sessions.begin() as session:
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_TWO).values(demo=True)
            )
