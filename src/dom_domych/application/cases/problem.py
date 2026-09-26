"""K09: обычная проблема, исходная аудитория и адресный запрос доказательств."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.contracts.base import PrincipalType, TrustedContext
from dom_domych.domain.audiences.models import AudienceScope, AudienceSnapshot, ScopeKind
from dom_domych.domain.polls.models import PollDefinition, PollKind, PollState
from dom_domych.domain.polls.policy import ProblemOutcome, ProblemPolicy


@dataclass(frozen=True, slots=True)
class ProblemCase:
    case_id: UUID
    house_id: UUID
    kind: str
    version: int
    status: str
    entrance: int | None
    floor: int | None
    poll_id: UUID | None = None
    audience_id: UUID | None = None


class ProblemCasePort(Protocol):
    async def get_problem(self, case_id: UUID, house_id: UUID) -> ProblemCase | None: ...


class AudienceResolver(Protocol):
    async def resolve(
        self,
        scope: AudienceScope,
        context: TrustedContext,
        *,
        operation_key: str,
        supersedes_id: UUID | None = None,
    ) -> AudienceSnapshot: ...


class ProblemStore(Protocol):
    async def open_atomic(
        self,
        case: ProblemCase,
        audience: AudienceSnapshot,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> ProblemCase: ...

    async def no_audience_atomic(
        self, case: ProblemCase, audience: AudienceSnapshot, operation_key: str
    ) -> ProblemCase: ...

    async def assess_atomic(
        self,
        case: ProblemCase,
        outcome: ProblemOutcome,
        yes_residents: tuple[UUID, ...],
        source_refs: tuple[str, ...],
        operation_key: str,
    ) -> ProblemCase: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class ProblemWorkflow:
    """K не считает голоса: итог и список «да» поступают из Z PollService."""

    def __init__(
        self,
        cases: ProblemCasePort,
        audiences: AudienceResolver,
        store: ProblemStore,
        clock: Clock,
    ) -> None:
        self.cases = cases
        self.audiences = audiences
        self.store = store
        self.clock = clock

    async def start(
        self,
        case_id: UUID,
        scope: AudienceScope,
        policy: ProblemPolicy,
        context: TrustedContext,
        *,
        operation_key: str,
    ) -> ProblemCase:
        if (
            "problem.open" not in context.capabilities
            or context.principal_type != PrincipalType.WORKER
            or not operation_key
        ):
            raise PermissionError("FORBIDDEN")
        case = await self.cases.get_problem(case_id, context.house_id)
        if case is None or case.kind != "problem" or case.status != "detected":
            raise ValueError("PROBLEM_NOT_READY")
        self._validate_scope(case, scope)
        audience = await self.audiences.resolve(
            scope, context, operation_key=f"{operation_key}:audience"
        )
        if audience.house_id != context.house_id:
            raise ValueError("WRONG_HOUSE")
        if audience.eligible_count == 0:
            return await self.store.no_audience_atomic(case, audience, operation_key)
        now = self.clock.now()
        poll = PollState(
            PollDefinition(
                poll_id=uuid4(),
                case_id=case_id,
                house_id=context.house_id,
                audience_id=audience.audience_id,
                kind=PollKind.PROBLEM_CONFIRMATION,
                policy=policy,
                subject_revision=case.version,
                eligible_residents=frozenset(member.resident_id for member in audience.members),
                opens_at=now,
                closes_at=now + policy.wait_period,
            )
        )
        targets = tuple(member.resident_id for member in audience.members)
        return await self.store.open_atomic(case, audience, poll, targets, operation_key)

    async def assess(
        self,
        case_id: UUID,
        poll_id: UUID,
        outcome: ProblemOutcome,
        yes_residents: tuple[UUID, ...],
        source_refs: tuple[str, ...],
        context: TrustedContext,
        *,
        operation_key: str,
    ) -> ProblemCase:
        if (
            "problem.assess" not in context.capabilities
            or context.principal_type != PrincipalType.WORKER
            or not operation_key
        ):
            raise PermissionError("FORBIDDEN")
        if outcome not in {ProblemOutcome.REQUEST_READY, ProblemOutcome.NEED_EVIDENCE}:
            raise ValueError("INVALID_PROBLEM_OUTCOME")
        if not source_refs:
            raise ValueError("ASSESSMENT_SOURCE_REQUIRED")
        case = await self.cases.get_problem(case_id, context.house_id)
        if case is None or case.poll_id != poll_id or case.status != "collecting":
            raise ValueError("STALE_POLL")
        if outcome == ProblemOutcome.NEED_EVIDENCE and len(yes_residents) == 0:
            # Нет личных адресатов: состояние фиксируется без публичного запроса фото.
            yes_residents = ()
        if outcome != ProblemOutcome.NEED_EVIDENCE:
            yes_residents = ()
        return await self.store.assess_atomic(
            case,
            outcome,
            tuple(dict.fromkeys(yes_residents)),
            source_refs,
            operation_key,
        )

    @staticmethod
    def _validate_scope(case: ProblemCase, scope: AudienceScope) -> None:
        if scope.kind == ScopeKind.HOUSE:
            if case.entrance is not None:
                raise ValueError("SCOPE_TOO_BROAD")
            return
        if scope.kind == ScopeKind.ENTRANCE and scope.entrance == case.entrance:
            return
        if (
            scope.kind == ScopeKind.FLOOR
            and scope.entrance == case.entrance
            and scope.floor == case.floor
        ):
            return
        raise ValueError("SCOPE_MISMATCH_OR_UNVERIFIED_RISER")
