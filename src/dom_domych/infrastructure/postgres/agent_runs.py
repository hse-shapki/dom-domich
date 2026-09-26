"""K04: короткие транзакции для runs, вопросов и краткого tool audit."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.continuation import PendingQuestion, RunSnapshot
from dom_domych.agent.runtime import RunOutcome
from dom_domych.infrastructure.postgres.agent_models import (
    AgentRunRow,
    AgentToolCallRow,
    PendingQuestionRow,
)


def _snapshot(row: AgentRunRow) -> RunSnapshot:
    return RunSnapshot(
        run_id=row.id,
        event_id=row.event_id,
        house_id=row.house_id,
        case_id=row.case_id,
        case_version=row.case_version,
        pending_question_id=row.pending_question_id,
        created_at=row.created_at,
    )


class PostgresRunStore:
    """Каждая операция использует новую AsyncSession; inference выполняется вне неё."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def save_run(self, run: RunSnapshot) -> RunSnapshot:
        async with self.sessions.begin() as session:
            statement = (
                insert(AgentRunRow)
                .values(
                    id=run.run_id,
                    house_id=run.house_id,
                    event_id=run.event_id,
                    case_id=run.case_id,
                    case_version=run.case_version,
                    pending_question_id=run.pending_question_id,
                    status="running",
                    created_at=run.created_at,
                )
                .on_conflict_do_nothing(index_elements=["house_id", "event_id"])
            )
            await session.execute(statement)
            stored = await session.scalar(
                select(AgentRunRow).where(
                    AgentRunRow.house_id == run.house_id,
                    AgentRunRow.event_id == run.event_id,
                )
            )
            assert stored is not None
            return _snapshot(stored)

    async def get_pending(
        self, house_id: UUID, case_id: UUID, actor_id: UUID, now: datetime
    ) -> PendingQuestion | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(PendingQuestionRow).where(
                    PendingQuestionRow.house_id == house_id,
                    PendingQuestionRow.case_id == case_id,
                    PendingQuestionRow.actor_id == actor_id,
                    PendingQuestionRow.status == "pending",
                    PendingQuestionRow.expires_at > now,
                )
            )
            if row is None:
                return None
            return PendingQuestion(
                question_id=row.id,
                house_id=row.house_id,
                case_id=row.case_id,
                actor_id=row.actor_id,
                expected_case_version=row.expected_case_version,
                requested_field=row.requested_field,
                expires_at=row.expires_at,
                answered_event_id=row.answered_event_id,
            )

    async def save_pending(self, question: PendingQuestion) -> None:
        async with self.sessions.begin() as session:
            session.add(
                PendingQuestionRow(
                    id=question.question_id,
                    house_id=question.house_id,
                    case_id=question.case_id,
                    actor_id=question.actor_id,
                    expected_case_version=question.expected_case_version,
                    requested_field=question.requested_field,
                    expires_at=question.expires_at,
                    status="pending",
                    answered_event_id=None,
                )
            )

    async def complete_run(self, run_id: UUID, house_id: UUID, outcome: RunOutcome) -> None:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(AgentRunRow)
                .where(
                    AgentRunRow.id == run_id,
                    AgentRunRow.house_id == house_id,
                )
                .with_for_update()
            )
            if row is None:
                raise ValueError("RUN_NOT_FOUND")
            if row.status != "running":
                if row.status == outcome.status:
                    return
                raise ValueError("RUN_ALREADY_COMPLETED")
            row.status = outcome.status
            for sequence, item in enumerate(outcome.audit, start=1):
                session.add(
                    AgentToolCallRow(
                        id=uuid4(),
                        run_id=run_id,
                        house_id=house_id,
                        sequence=sequence,
                        tool_name=item.name,
                        outcome=item.outcome,
                        entity_version=item.entity_version,
                        source_refs=list(item.source_refs),
                    )
                )

    async def invalidate_pending(self, question_id: UUID, house_id: UUID) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(PendingQuestionRow)
                .where(
                    PendingQuestionRow.id == question_id,
                    PendingQuestionRow.house_id == house_id,
                    PendingQuestionRow.status == "pending",
                )
                .values(status="invalidated")
            )

    async def mark_answered(
        self, question_id: UUID, house_id: UUID, actor_id: UUID, event_id: UUID
    ) -> bool:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(PendingQuestionRow)
                .where(
                    PendingQuestionRow.id == question_id,
                    PendingQuestionRow.house_id == house_id,
                    PendingQuestionRow.actor_id == actor_id,
                )
                .with_for_update()
            )
            if row is None:
                return False
            if row.status == "answered":
                return row.answered_event_id == event_id
            if row.status != "pending":
                return False
            row.status = "answered"
            row.answered_event_id = event_id
            return True
