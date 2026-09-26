"""K04 persistence: запускать на мигрированной PostgreSQL через TEST_DATABASE_URL."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from dom_domych.agent.continuation import PendingQuestion, RunSnapshot
from dom_domych.agent.runtime import RunOutcome, ToolAudit
from dom_domych.infrastructure.postgres.agent_models import (
    AgentRunRow,
    AgentToolCallRow,
    PendingQuestionRow,
)
from dom_domych.infrastructure.postgres.agent_runs import PostgresRunStore
from dom_domych.infrastructure.postgres.models import HouseRow, ResidentRow
from dom_domych.infrastructure.postgres.session import database_lifespan


@pytest.mark.asyncio
async def test_agent_run_survives_new_store_and_is_house_scoped() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, actor_id, event_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add(
                HouseRow(id=house_id, address="Тестовый дом K04", timezone="UTC", demo=True)
            )
            session.add(
                ResidentRow(
                    id=actor_id,
                    display_name="Тестовый житель K04",
                    active_house_id=house_id,
                )
            )
        try:
            first = PostgresRunStore(sessions)
            run = RunSnapshot(
                run_id=uuid4(),
                event_id=event_id,
                house_id=house_id,
                case_id=uuid4(),
                case_version=2,
                pending_question_id=None,
                created_at=now,
            )
            saved = await first.save_run(run)
            replay = await PostgresRunStore(sessions).save_run(
                RunSnapshot(
                    run_id=uuid4(),
                    event_id=event_id,
                    house_id=house_id,
                    case_id=run.case_id,
                    case_version=2,
                    pending_question_id=None,
                    created_at=now + timedelta(seconds=1),
                )
            )
            assert replay.run_id == saved.run_id

            question = PendingQuestion(
                question_id=uuid4(),
                house_id=house_id,
                case_id=run.case_id,
                actor_id=actor_id,
                expected_case_version=2,
                requested_field="entrance",
                expires_at=now + timedelta(hours=1),
            )
            await first.save_pending(question)
            assert (
                await PostgresRunStore(sessions).get_pending(house_id, run.case_id, actor_id, now)
                == question
            )
            assert await first.get_pending(uuid4(), run.case_id, actor_id, now) is None
            assert (
                await first.get_pending(house_id, run.case_id, actor_id, now + timedelta(hours=2))
                is None
            )
            assert (
                await first.mark_answered(question.question_id, uuid4(), actor_id, uuid4()) is False
            )
            answer_event = uuid4()
            assert (
                await first.mark_answered(question.question_id, house_id, actor_id, answer_event)
                is True
            )
            assert (
                await PostgresRunStore(sessions).get_pending(house_id, run.case_id, actor_id, now)
                is None
            )
            assert (
                await first.mark_answered(question.question_id, house_id, actor_id, answer_event)
                is True
            )

            outcome = RunOutcome(
                "completed", "Не горит лампа", (ToolAudit("case.search", "ok", 2, ("msg:1",)),)
            )
            await PostgresRunStore(sessions).complete_run(run.run_id, house_id, outcome)
            async with sessions() as session:
                row = await session.get(AgentRunRow, run.run_id)
                assert row is not None and row.status == "completed"
                calls = (
                    await session.scalars(
                        select(AgentToolCallRow).where(AgentToolCallRow.run_id == run.run_id)
                    )
                ).all()
                assert len(calls) == 1
                assert calls[0].source_refs == ["msg:1"]
        finally:
            async with sessions.begin() as session:
                await session.execute(
                    delete(AgentToolCallRow).where(AgentToolCallRow.house_id == house_id)
                )
                await session.execute(
                    delete(PendingQuestionRow).where(PendingQuestionRow.house_id == house_id)
                )
                await session.execute(delete(AgentRunRow).where(AgentRunRow.house_id == house_id))
                await session.execute(delete(ResidentRow).where(ResidentRow.id == actor_id))
                await session.execute(delete(HouseRow).where(HouseRow.id == house_id))
