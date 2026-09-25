from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from dom_domych.agent.continuation import ContextBuilder, FakeRunStore, PendingQuestion
from dom_domych.agent.contracts import (
    CaseAttachMessage,
    CaseCreate,
    CaseKind,
    Continuation,
    ContinuationEvent,
    TrustedContext,
)
from dom_domych.agent.fakes import FakeCasePort
from dom_domych.contracts.base import ExecutionMode, PrincipalType


def _context() -> TrustedContext:
    return TrustedContext(
        house_id=uuid4(),
        actor_id=uuid4(),
        event_id=uuid4(),
        run_id=uuid4(),
        capabilities=frozenset(),
        principal_type=PrincipalType.RESIDENT,
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )


@pytest.mark.asyncio
async def test_new_event_uses_current_case_version_after_restarting_coordinator() -> None:
    context = _context()
    cases = FakeCasePort()
    runs = FakeRunStore()
    case = await cases.create(
        CaseCreate(
            kind=CaseKind.PROBLEM,
            title="Лампа на лестнице",
            description="Темно у лифта",
            source_message_id=uuid4(),
            operation_id=uuid4(),
        ),
        context,
    )
    builder = ContextBuilder(cases, runs)
    first = await builder.build(context, case_id=case.case_id, now=datetime.now(UTC))
    await cases.attach_message(
        CaseAttachMessage(
            case_id=case.case_id,
            message_id=uuid4(),
            expected_version=1,
            operation_id=uuid4(),
        ),
        context,
    )
    new_context = context.model_copy(update={"event_id": uuid4(), "run_id": uuid4()})
    event = Continuation(
        event=ContinuationEvent.EVIDENCE_ADDED,
        house_id=context.house_id,
        case_id=case.case_id,
        case_version=1,
        event_id=new_context.event_id,
        occurred_at=datetime.now(UTC),
    )
    resumed = await ContextBuilder(cases, runs).continue_from_event(event, new_context)
    assert first.run.case_version == 1
    assert resumed.run.case_version == 2
    assert resumed.run.run_id != first.run.run_id


@pytest.mark.asyncio
async def test_pending_question_is_actor_scoped_and_foreign_house_is_hidden() -> None:
    context = _context()
    cases = FakeCasePort()
    runs = FakeRunStore()
    case = await cases.create(
        CaseCreate(
            kind=CaseKind.PROBLEM,
            title="Лампа на лестнице",
            description="Темно у лифта",
            source_message_id=uuid4(),
            operation_id=uuid4(),
        ),
        context,
    )
    await runs.save_pending(
        PendingQuestion(
            question_id=uuid4(),
            house_id=context.house_id,
            case_id=case.case_id,
            actor_id=context.actor_id,
            expected_case_version=1,
            requested_field="entrance",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    own = await ContextBuilder(cases, runs).build(
        context, case_id=case.case_id, now=datetime.now(UTC)
    )
    assert own.pending_question is not None
    other_actor = context.model_copy(update={"actor_id": uuid4()})
    other = await ContextBuilder(cases, runs).build(
        other_actor, case_id=case.case_id, now=datetime.now(UTC)
    )
    assert other.pending_question is None
    other_house = context.model_copy(update={"house_id": uuid4()})
    with pytest.raises(ValueError, match="CASE_NOT_FOUND"):
        await ContextBuilder(cases, runs).build(
            other_house, case_id=case.case_id, now=datetime.now(UTC)
        )
