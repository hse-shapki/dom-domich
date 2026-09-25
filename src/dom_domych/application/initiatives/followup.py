"""Напоминания и финальная позиция жителей по текущей редакции инициативы."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from dom_domych.domain.initiatives.models import InitiativeConflict, InitiativeState
from dom_domych.domain.polls.models import PollKind, PollState, PollStatus
from dom_domych.domain.polls.policy import InitiativeOutcome, InitiativePolicy


@dataclass(frozen=True, slots=True)
class ReminderPolicy:
    revision: str
    min_interval: timedelta
    max_per_resident: int
    stop_before_deadline: timedelta
    demo: bool

    def __post_init__(self) -> None:
        if (
            not self.revision
            or self.min_interval <= timedelta(0)
            or self.max_per_resident <= 0
            or self.stop_before_deadline < timedelta(0)
        ):
            raise ValueError("invalid reminder policy")


def demo_reminder_policy() -> ReminderPolicy:
    """Временные параметры показа; не политика уведомлений реального дома."""

    return ReminderPolicy("demo-reminder-v1", timedelta(minutes=30), 2, timedelta(minutes=5), True)


@dataclass(frozen=True, slots=True)
class InitiativeDecision:
    case_id: UUID
    house_id: UUID
    initiative_revision: int
    poll_id: UUID
    poll_version: int
    outcome: InitiativeOutcome
    decided_at: datetime
    policy_revision: str
    demo: bool


class Clock(Protocol):
    def now(self) -> datetime: ...


class CurrentDeliveryRights(Protocol):
    async def filter_reachable(
        self, house_id: UUID, resident_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        """Сейчас подтверждённые/активные жители с доступной личкой; denominator не меняется."""
        ...


class FollowupRepository(Protocol):
    async def enqueue_reminders_atomic(
        self,
        poll_id: UUID,
        house_id: UUID,
        expected_poll_version: int,
        candidate_ids: tuple[UUID, ...],
        now: datetime,
        policy: ReminderPolicy,
        operation_key: str,
    ) -> tuple[UUID, ...]:
        """Под lock перепроверяет открытость/ответы/лимит и сохраняет outbox."""
        ...

    async def save_decision_once(
        self, decision: InitiativeDecision, operation_key: str
    ) -> InitiativeDecision:
        """В одной UoW сохраняет решение и event supported/not_supported."""
        ...


class InitiativeFollowupService:
    def __init__(
        self,
        repository: FollowupRepository,
        rights: CurrentDeliveryRights,
        clock: Clock,
    ) -> None:
        self.repository = repository
        self.rights = rights
        self.clock = clock

    async def plan_reminders(
        self,
        state: InitiativeState,
        poll: PollState,
        policy: ReminderPolicy,
        *,
        operation_key: str,
    ) -> tuple[UUID, ...]:
        self._validate_current_poll(state, poll)
        if not operation_key:
            raise ValueError("operation key is required")
        now = self.clock.now()
        if (
            poll.status is not PollStatus.OPEN
            or now >= poll.definition.closes_at - policy.stop_before_deadline
        ):
            return ()
        answered = {answer.resident_id for answer in poll.answers}
        unanswered = tuple(
            sorted(
                poll.definition.eligible_residents - answered,
                key=lambda item: item.bytes,
            )
        )
        reachable = await self.rights.filter_reachable(state.house_id, unanswered)
        safe_targets = tuple(sorted(set(reachable) & set(unanswered), key=lambda item: item.bytes))
        return await self.repository.enqueue_reminders_atomic(
            poll.definition.poll_id,
            state.house_id,
            poll.version,
            safe_targets,
            now,
            policy,
            operation_key,
        )

    async def finalize_position(
        self,
        state: InitiativeState,
        poll: PollState,
        *,
        operation_key: str,
    ) -> InitiativeDecision:
        self._validate_current_poll(state, poll)
        if not operation_key:
            raise ValueError("operation key is required")
        if poll.status is not PollStatus.CLOSED:
            raise InitiativeConflict("initiative poll is not finalized")
        outcome = poll.outcome
        policy = poll.definition.policy
        if not isinstance(outcome, InitiativeOutcome) or not isinstance(policy, InitiativePolicy):
            raise InitiativeConflict("initiative poll has invalid outcome or policy")
        return await self.repository.save_decision_once(
            InitiativeDecision(
                case_id=state.case_id,
                house_id=state.house_id,
                initiative_revision=state.current.revision,
                poll_id=poll.definition.poll_id,
                poll_version=poll.version,
                outcome=outcome,
                decided_at=self.clock.now(),
                policy_revision=policy.revision,
                demo=policy.demo,
            ),
            operation_key,
        )

    @staticmethod
    def _validate_current_poll(state: InitiativeState, poll: PollState) -> None:
        definition = poll.definition
        if (
            definition.kind is not PollKind.INITIATIVE_POSITION
            or definition.house_id != state.house_id
            or definition.case_id != state.case_id
            or definition.poll_id != state.current.poll_id
            or definition.audience_id != state.current.audience_id
            or definition.subject_revision != state.current.revision
        ):
            raise InitiativeConflict("poll does not match current initiative revision")
