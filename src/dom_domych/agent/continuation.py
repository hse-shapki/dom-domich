"""Построение минимального контекста и продолжение после нового события."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.agent.contracts import CasePort, CaseView, Continuation, TrustedContext


@dataclass(frozen=True, slots=True)
class PendingQuestion:
    question_id: UUID
    house_id: UUID
    case_id: UUID
    actor_id: UUID
    expected_case_version: int
    requested_field: str
    expires_at: datetime
    answered_event_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    run_id: UUID
    event_id: UUID
    house_id: UUID
    case_id: UUID | None
    case_version: int | None
    pending_question_id: UUID | None


class RunStore(Protocol):
    """Постоянное хранилище реализует A/K persistence на G1."""

    async def save_run(self, run: RunSnapshot) -> None: ...
    async def get_pending(
        self, house_id: UUID, case_id: UUID, actor_id: UUID, now: datetime
    ) -> PendingQuestion | None: ...
    async def save_pending(self, question: PendingQuestion) -> None: ...


class FakeRunStore:
    """Тестовый port сохраняет данные между экземплярами coordinator в одном процессе."""

    def __init__(self) -> None:
        self.runs: dict[UUID, RunSnapshot] = {}
        self.questions: dict[UUID, PendingQuestion] = {}

    async def save_run(self, run: RunSnapshot) -> None:
        self.runs[run.run_id] = run

    async def get_pending(
        self, house_id: UUID, case_id: UUID, actor_id: UUID, now: datetime
    ) -> PendingQuestion | None:
        return next(
            (
                question
                for question in self.questions.values()
                if question.house_id == house_id
                and question.case_id == case_id
                and question.actor_id == actor_id
                and question.answered_event_id is None
                and question.expires_at > now
            ),
            None,
        )

    async def save_pending(self, question: PendingQuestion) -> None:
        self.questions[question.question_id] = question


@dataclass(frozen=True, slots=True)
class BuiltContext:
    run: RunSnapshot
    case: CaseView | None
    pending_question: PendingQuestion | None
    prompt_facts: tuple[str, ...]


class ContextBuilder:
    """Читает актуальное дело и вопрос только в границах доверенного дома/actor."""

    def __init__(self, cases: CasePort, runs: RunStore) -> None:
        self.cases = cases
        self.runs = runs

    async def build(
        self, context: TrustedContext, *, case_id: UUID | None, now: datetime
    ) -> BuiltContext:
        case = await self.cases.get(case_id, context) if case_id is not None else None
        if case_id is not None and case is None:
            raise ValueError("CASE_NOT_FOUND")
        pending = (
            await self.runs.get_pending(context.house_id, case.case_id, context.actor_id, now)
            if case is not None
            else None
        )
        run = RunSnapshot(
            run_id=uuid4(),
            event_id=context.event_id,
            house_id=context.house_id,
            case_id=case.case_id if case else None,
            case_version=case.version if case else None,
            pending_question_id=pending.question_id if pending else None,
        )
        await self.runs.save_run(run)
        facts: tuple[str, ...] = (
            (f"Дело {case.case_id}; версия {case.version}; состояние {case.status}.",)
            if case
            else ()
        )
        if pending is not None:
            facts += (f"Ожидается поле: {pending.requested_field}.",)
        return BuiltContext(run, case, pending, facts)

    async def continue_from_event(
        self, event: Continuation, context: TrustedContext
    ) -> BuiltContext:
        if event.house_id != context.house_id or event.event_id != context.event_id:
            raise ValueError("EVENT_CONTEXT_MISMATCH")
        # Версия события — только историческая подсказка. Читаем текущее состояние.
        return await self.build(context, case_id=event.case_id, now=event.occurred_at)
