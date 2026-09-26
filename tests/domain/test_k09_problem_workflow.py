"""K09: snapshot Z, пустая категория и приватный запрос evidence на fake store."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from dom_domych.application.cases.problem import ProblemCase, ProblemWorkflow
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.domain.audiences.models import (
    AudienceMember,
    AudienceScope,
    AudienceSnapshot,
    ScopeKind,
)
from dom_domych.domain.polls.models import PollState
from dom_domych.domain.polls.policy import ProblemOutcome, ProblemPolicy

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeCases:
    def __init__(self, case: ProblemCase) -> None:
        self.case = case

    async def get_problem(self, case_id: UUID, house_id: UUID) -> ProblemCase | None:
        if (case_id, house_id) == (self.case.case_id, self.case.house_id):
            return self.case
        return None


class FakeAudiences:
    def __init__(self, members: tuple[AudienceMember, ...]) -> None:
        self.members = members

    async def resolve(
        self,
        scope: AudienceScope,
        context: TrustedContext,
        *,
        operation_key: str,
        supersedes_id: UUID | None = None,
    ) -> AudienceSnapshot:
        return AudienceSnapshot(uuid4(), context.house_id, scope, 1, self.members, NOW)


class FakeStore:
    def __init__(self, cases: FakeCases) -> None:
        self.cases = cases
        self.poll: PollState | None = None
        self.targets: tuple[UUID, ...] = ()
        self.private_evidence_targets: tuple[UUID, ...] = ()
        self.assessment_sources: tuple[str, ...] = ()

    async def open_atomic(
        self,
        case: ProblemCase,
        audience: AudienceSnapshot,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> ProblemCase:
        self.poll = poll
        self.targets = notification_targets
        self.cases.case = replace(
            case,
            status="collecting",
            version=case.version + 1,
            poll_id=poll.definition.poll_id,
            audience_id=audience.audience_id,
        )
        return self.cases.case

    async def no_audience_atomic(
        self, case: ProblemCase, audience: AudienceSnapshot, operation_key: str
    ) -> ProblemCase:
        self.cases.case = replace(
            case,
            status="needs_evidence",
            version=case.version + 1,
            audience_id=audience.audience_id,
        )
        return self.cases.case

    async def assess_atomic(
        self,
        case: ProblemCase,
        outcome: ProblemOutcome,
        yes_residents: tuple[UUID, ...],
        source_refs: tuple[str, ...],
        operation_key: str,
    ) -> ProblemCase:
        self.private_evidence_targets = yes_residents
        self.assessment_sources = source_refs
        status = "request_ready" if outcome == ProblemOutcome.REQUEST_READY else "needs_evidence"
        self.cases.case = replace(case, status=status, version=case.version + 1)
        return self.cases.case


def _context(house_id: UUID) -> TrustedContext:
    return TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=house_id,
        actor_id=uuid4(),
        principal_type=PrincipalType.WORKER,
        capabilities=frozenset({"problem.open", "problem.assess"}),
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )


def _setup(
    members: tuple[AudienceMember, ...],
) -> tuple[ProblemWorkflow, FakeCases, FakeStore, TrustedContext]:
    house_id = uuid4()
    cases = FakeCases(ProblemCase(uuid4(), house_id, "problem", 1, "detected", 2, 3))
    store = FakeStore(cases)
    return (
        ProblemWorkflow(cases, FakeAudiences(members), store, FixedClock()),
        cases,
        store,
        _context(house_id),
    )


@pytest.mark.asyncio
async def test_problem_poll_uses_all_eligible_and_five_hours() -> None:
    members = tuple(AudienceMember(uuid4(), reachable_at_snapshot=index == 0) for index in range(5))
    workflow, cases, store, context = _setup(members)
    policy = ProblemPolicy("demo-problem-v1", Decimal("0.2"), timedelta(hours=5), True)
    case = await workflow.start(
        cases.case.case_id,
        AudienceScope(ScopeKind.FLOOR, entrance=2, floor=3),
        policy,
        context,
        operation_key="open-1",
    )
    assert case.status == "collecting" and store.poll is not None
    assert len(store.poll.definition.eligible_residents) == 5
    assert store.poll.definition.closes_at == NOW + timedelta(hours=5)
    assert len(store.targets) == 5
    yes = members[0].resident_id
    assessed = await workflow.assess(
        case.case_id,
        case.poll_id,
        ProblemOutcome.NEED_EVIDENCE,
        (yes, yes),
        ("poll:fixture",),
        context,
        operation_key="assess-1",
    )
    assert assessed.status == "needs_evidence"
    assert store.private_evidence_targets == (yes,)
    assert store.assessment_sources == ("poll:fixture",)


@pytest.mark.asyncio
async def test_empty_category_does_not_open_poll_or_fake_support() -> None:
    workflow, cases, store, context = _setup(())
    policy = ProblemPolicy("demo-problem-v1", Decimal("0.2"), timedelta(hours=5), True)
    case = await workflow.start(
        cases.case.case_id,
        AudienceScope(ScopeKind.ENTRANCE, entrance=2),
        policy,
        context,
        operation_key="open-empty",
    )
    assert case.status == "needs_evidence" and store.poll is None
    other_workflow, other_cases, _, other_context = _setup(())
    with pytest.raises(ValueError, match="SCOPE_TOO_BROAD"):
        await other_workflow.start(
            other_cases.case.case_id,
            AudienceScope(ScopeKind.HOUSE),
            policy,
            other_context,
            operation_key="wrong-scope",
        )
