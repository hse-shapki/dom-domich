"""Детерминированные переходы опроса; repository применяет их атомарно под lock."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from dom_domych.domain.polls.policy import (
    InitiativeOutcome,
    InitiativePolicy,
    ProblemOutcome,
    ProblemPolicy,
    ResolutionOutcome,
    ResolutionPolicy,
    VoteTally,
    evaluate_initiative,
    evaluate_problem,
    evaluate_resolution,
    received_during_poll,
)


class PollKind(StrEnum):
    PROBLEM_CONFIRMATION = "problem_confirmation"
    INITIATIVE_POSITION = "initiative_position"
    RESOLUTION_CHECK = "resolution_check"


class PollStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class VoteChoice(StrEnum):
    YES = "yes"
    NO = "no"


class AnswerStatus(StrEnum):
    RECORDED = "recorded"
    CHANGED = "changed"
    DUPLICATE = "duplicate"
    NOT_ELIGIBLE = "not_eligible"
    LATE = "late"
    CLOSED = "closed"


type PollPolicy = ProblemPolicy | InitiativePolicy | ResolutionPolicy
type PollOutcome = ProblemOutcome | InitiativeOutcome | ResolutionOutcome


@dataclass(frozen=True, slots=True)
class PollDefinition:
    poll_id: UUID
    case_id: UUID
    house_id: UUID
    audience_id: UUID
    kind: PollKind
    policy: PollPolicy
    subject_revision: int
    eligible_residents: frozenset[UUID]
    opens_at: datetime
    closes_at: datetime

    def __post_init__(self) -> None:
        expected_policy = {
            PollKind.PROBLEM_CONFIRMATION: ProblemPolicy,
            PollKind.INITIATIVE_POSITION: InitiativePolicy,
            PollKind.RESOLUTION_CHECK: ResolutionPolicy,
        }[self.kind]
        if not isinstance(self.policy, expected_policy):
            raise TypeError("poll kind and policy do not match")
        if self.subject_revision <= 0:
            raise ValueError("subject_revision must be positive")
        if self.opens_at.tzinfo is None or self.opens_at.utcoffset() != timedelta(0):
            raise ValueError("opens_at must use UTC")
        if self.closes_at.tzinfo is None or self.closes_at.utcoffset() != timedelta(0):
            raise ValueError("closes_at must use UTC")
        if self.closes_at <= self.opens_at:
            raise ValueError("poll must have a positive window")
        if (
            isinstance(self.policy, ProblemPolicy)
            and self.closes_at - self.opens_at != self.policy.wait_period
        ):
            raise ValueError("problem poll window must match frozen policy")


@dataclass(frozen=True, slots=True)
class PollAnswer:
    resident_id: UUID
    choice: VoteChoice
    source_event_id: UUID
    received_at: datetime
    revision: int


@dataclass(frozen=True, slots=True)
class AnswerResult:
    status: AnswerStatus
    poll_version: int
    current_answer: VoteChoice | None


@dataclass(frozen=True, slots=True)
class PollMutation:
    state: "PollState"
    answer_result: AnswerResult | None = None
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PollState:
    definition: PollDefinition
    answers: tuple[PollAnswer, ...] = ()
    answer_history: tuple[PollAnswer, ...] = ()
    processed_event_ids: frozenset[UUID] = frozenset()
    status: PollStatus = PollStatus.OPEN
    version: int = 1
    outcome: PollOutcome | None = None
    threshold_emitted: bool = False

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise ValueError("poll version must be positive")
        ids = [answer.resident_id for answer in self.answers]
        if len(ids) != len(set(ids)) or not set(ids) <= self.definition.eligible_residents:
            raise ValueError("poll answers must belong to unique eligible residents")
        if self.status == PollStatus.OPEN and self.outcome is not None:
            raise ValueError("open poll cannot have final outcome")
        if self.status == PollStatus.CLOSED and self.outcome is None:
            raise ValueError("closed poll needs final outcome")
        if self.status == PollStatus.CANCELLED and self.outcome is not None:
            raise ValueError("cancelled poll cannot have outcome")

    @property
    def tally(self) -> VoteTally:
        return VoteTally(
            eligible=len(self.definition.eligible_residents),
            yes=sum(answer.choice == VoteChoice.YES for answer in self.answers),
            no=sum(answer.choice == VoteChoice.NO for answer in self.answers),
        )

    def record_answer(
        self,
        actor_id: UUID,
        choice: VoteChoice,
        source_event_id: UUID,
        received_at: datetime,
    ) -> PollMutation:
        """Повтор события и повтор того же ответа не дают нового голоса."""

        if source_event_id in self.processed_event_ids:
            current = next((a.choice for a in self.answers if a.resident_id == actor_id), None)
            return PollMutation(self, AnswerResult(AnswerStatus.DUPLICATE, self.version, current))
        if actor_id not in self.definition.eligible_residents:
            return PollMutation(self, AnswerResult(AnswerStatus.NOT_ELIGIBLE, self.version, None))
        if not received_during_poll(
            received_at, self.definition.opens_at, self.definition.closes_at
        ):
            return PollMutation(self, AnswerResult(AnswerStatus.LATE, self.version, None))
        if self.status != PollStatus.OPEN:
            return PollMutation(self, AnswerResult(AnswerStatus.CLOSED, self.version, None))

        previous = next((a for a in self.answers if a.resident_id == actor_id), None)
        if previous is not None and previous.choice == choice:
            return PollMutation(self, AnswerResult(AnswerStatus.DUPLICATE, self.version, choice))
        answer = PollAnswer(
            resident_id=actor_id,
            choice=choice,
            source_event_id=source_event_id,
            received_at=received_at,
            revision=1 if previous is None else previous.revision + 1,
        )
        answers = tuple(
            sorted(
                (item for item in self.answers if item.resident_id != actor_id),
                key=lambda item: item.resident_id.bytes,
            )
        ) + (answer,)
        answers = tuple(sorted(answers, key=lambda item: item.resident_id.bytes))
        updated = replace(
            self,
            answers=answers,
            answer_history=self.answer_history + (answer,),
            processed_event_ids=self.processed_event_ids | {source_event_id},
            version=self.version + 1,
        )
        events: tuple[str, ...] = ()
        if self.definition.kind == PollKind.PROBLEM_CONFIRMATION:
            policy = self.definition.policy
            if not isinstance(policy, ProblemPolicy):
                raise ValueError("problem poll has incompatible policy")
            if (
                evaluate_problem(updated.tally, policy, expired=False)
                == ProblemOutcome.REQUEST_READY
            ):
                updated = replace(
                    updated,
                    status=PollStatus.CLOSED,
                    outcome=ProblemOutcome.REQUEST_READY,
                    threshold_emitted=True,
                )
                events = ("poll.threshold_reached",)
        result_status = AnswerStatus.RECORDED if previous is None else AnswerStatus.CHANGED
        return PollMutation(updated, AnswerResult(result_status, updated.version, choice), events)

    def finalize(self, now: datetime) -> PollMutation:
        """Финализировать после дренажа всех inbox-событий, полученных до closes_at."""

        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("now must use UTC")
        if self.status != PollStatus.OPEN:
            return PollMutation(self)
        if now < self.definition.closes_at:
            raise ValueError("poll deadline has not arrived")
        policy = self.definition.policy
        if isinstance(policy, ProblemPolicy):
            outcome: PollOutcome = evaluate_problem(self.tally, policy, expired=True)
        elif isinstance(policy, InitiativePolicy):
            outcome = evaluate_initiative(self.tally, policy, finalized=True)
        else:
            outcome = evaluate_resolution(self.tally, policy, finalized=True)
        updated = replace(self, status=PollStatus.CLOSED, version=self.version + 1, outcome=outcome)
        return PollMutation(updated, events=("poll.finalized",))

    def cancel(self) -> PollMutation:
        """Инвалидирует старые голоса/кнопки при изменении предмета опроса."""

        if self.status != PollStatus.OPEN:
            return PollMutation(self)
        updated = replace(self, status=PollStatus.CANCELLED, version=self.version + 1)
        return PollMutation(updated, events=("poll.cancelled",))
