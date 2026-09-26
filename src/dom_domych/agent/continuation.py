"""Построение минимального контекста и продолжение после нового события."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.agent.contracts import CasePort, CaseView, Continuation, TrustedContext
from dom_domych.agent.runtime import AgentMode, AgentRuntime, RunOutcome


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
    created_at: datetime


class RunStore(Protocol):
    """Постоянное хранилище реализует A/K persistence на G1."""

    async def save_run(self, run: RunSnapshot) -> RunSnapshot: ...
    async def get_pending(
        self, house_id: UUID, case_id: UUID, actor_id: UUID, now: datetime
    ) -> PendingQuestion | None: ...
    async def save_pending(self, question: PendingQuestion) -> None: ...
    async def complete_run(self, run_id: UUID, house_id: UUID, outcome: RunOutcome) -> None: ...
    async def invalidate_pending(self, question_id: UUID, house_id: UUID) -> None: ...
    async def mark_answered(
        self, question_id: UUID, house_id: UUID, actor_id: UUID, event_id: UUID
    ) -> bool: ...


class FakeRunStore:
    """Тестовый port сохраняет данные между экземплярами coordinator в одном процессе."""

    def __init__(self) -> None:
        self.runs: dict[UUID, RunSnapshot] = {}
        self.questions: dict[UUID, PendingQuestion] = {}
        self.outcomes: dict[UUID, RunOutcome] = {}

    async def save_run(self, run: RunSnapshot) -> RunSnapshot:
        for previous in self.runs.values():
            if previous.house_id == run.house_id and previous.event_id == run.event_id:
                return previous
        self.runs[run.run_id] = run
        return run

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
        for previous in self.questions.values():
            if (previous.house_id, previous.case_id, previous.actor_id) == (
                question.house_id,
                question.case_id,
                question.actor_id,
            ) and previous.answered_event_id is None:
                raise ValueError("PENDING_QUESTION_EXISTS")
        self.questions[question.question_id] = question

    async def complete_run(self, run_id: UUID, house_id: UUID, outcome: RunOutcome) -> None:
        run = self.runs.get(run_id)
        if run is None or run.house_id != house_id:
            raise ValueError("RUN_NOT_FOUND")
        self.outcomes[run_id] = outcome

    async def invalidate_pending(self, question_id: UUID, house_id: UUID) -> None:
        question = self.questions.get(question_id)
        if question is not None and question.house_id == house_id:
            self.questions.pop(question_id)

    async def mark_answered(
        self, question_id: UUID, house_id: UUID, actor_id: UUID, event_id: UUID
    ) -> bool:
        question = self.questions.get(question_id)
        if question is None or (question.house_id, question.actor_id) != (house_id, actor_id):
            return False
        if question.answered_event_id is not None:
            return question.answered_event_id == event_id
        self.questions[question_id] = PendingQuestion(
            question_id=question.question_id,
            house_id=question.house_id,
            case_id=question.case_id,
            actor_id=question.actor_id,
            expected_case_version=question.expected_case_version,
            requested_field=question.requested_field,
            expires_at=question.expires_at,
            answered_event_id=event_id,
        )
        return True


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
            if case is not None and context.actor_id is not None
            else None
        )
        if (
            pending is not None
            and case is not None
            and pending.expected_case_version != case.version
        ):
            await self.runs.invalidate_pending(pending.question_id, context.house_id)
            pending = None
        run = RunSnapshot(
            run_id=uuid4(),
            event_id=context.event_id,
            house_id=context.house_id,
            case_id=case.case_id if case else None,
            case_version=case.version if case else None,
            pending_question_id=pending.question_id if pending else None,
            created_at=now,
        )
        run = await self.runs.save_run(run)
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


class AgentCoordinator:
    """Сохраняет начало и итог run, не удерживая SQL-транзакцию во время LLM."""

    def __init__(self, builder: ContextBuilder, runtime: AgentRuntime) -> None:
        self.builder = builder
        self.runtime = runtime

    async def run_event(
        self,
        messages: list[dict[str, object]],
        context: TrustedContext,
        mode: AgentMode,
        *,
        case_id: UUID | None,
        now: datetime,
    ) -> RunOutcome:
        built = await self.builder.build(context, case_id=case_id, now=now)
        run_context = context.model_copy(update={"run_id": built.run.run_id})
        prepared = list(messages)
        if built.prompt_facts:
            prepared.insert(0, {"role": "system", "content": " ".join(built.prompt_facts)})
        outcome = await self.runtime.run(prepared, run_context, mode)
        await self.builder.runs.complete_run(built.run.run_id, context.house_id, outcome)
        if outcome.status == "completed" and built.pending_question is not None:
            assert context.actor_id is not None
            await self.builder.runs.mark_answered(
                built.pending_question.question_id,
                context.house_id,
                context.actor_id,
                context.event_id,
            )
        return outcome
