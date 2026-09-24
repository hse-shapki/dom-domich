"""Команды опроса; атомарное применение перехода выполняет repository."""

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.domain.audiences.models import AudienceSnapshot
from dom_domych.domain.polls.models import (
    PollDefinition,
    PollKind,
    PollMutation,
    PollPolicy,
    PollState,
    VoteChoice,
)
from dom_domych.domain.polls.policy import ProblemPolicy


class TrustedHouseContext(Protocol):
    @property
    def house_id(self) -> UUID: ...


class TrustedCallbackContext(TrustedHouseContext, Protocol):
    @property
    def actor_id(self) -> UUID: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class PollRepository(Protocol):
    async def open_once(
        self,
        state: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> PollState:
        """Атомарно сохраняет poll, deadline job и outbox; повтор key не создаёт их вновь."""
        ...

    async def record_answer_atomic(
        self,
        poll_id: UUID,
        house_id: UUID,
        actor_id: UUID,
        choice: VoteChoice,
        source_event_id: UUID,
        received_at: datetime,
    ) -> PollMutation:
        """Под lock вызывает PollState.record_answer и сохраняет event единожды."""
        ...

    async def finalize_atomic(
        self, poll_id: UUID, house_id: UUID, now: datetime
    ) -> PollMutation:
        """После дренажа predeadline inbox вызывает PollState.finalize под lock."""
        ...


class PollService:
    """Не принимает actor или house ID из аргументов модели при записи голоса."""

    def __init__(self, repository: PollRepository, clock: Clock) -> None:
        self.repository = repository
        self.clock = clock

    async def open(
        self,
        case_id: UUID,
        audience: AudienceSnapshot,
        kind: PollKind,
        policy: PollPolicy,
        subject_revision: int,
        context: TrustedHouseContext,
        *,
        operation_key: str,
        window: timedelta | None = None,
    ) -> PollState:
        """Фиксирует состав и правило; окно других опросов задаёт доверенный handler."""

        if not operation_key:
            raise ValueError("operation_key is required")
        if audience.house_id != context.house_id:
            raise ValueError("audience belongs to another house")
        if audience.eligible_count == 0:
            raise ValueError("cannot open poll without an eligible audience")
        if isinstance(policy, ProblemPolicy):
            if window is not None:
                raise ValueError("problem poll window comes from policy")
            duration = policy.wait_period
        else:
            if window is None or window <= timedelta(0):
                raise ValueError("trusted window is required for this poll")
            duration = window
        opens_at = self.clock.now()
        definition = PollDefinition(
            poll_id=uuid4(),
            case_id=case_id,
            house_id=context.house_id,
            audience_id=audience.audience_id,
            kind=kind,
            policy=policy,
            subject_revision=subject_revision,
            eligible_residents=frozenset(
                member.resident_id for member in audience.members
            ),
            opens_at=opens_at,
            closes_at=opens_at + duration,
        )
        targets = tuple(member.resident_id for member in audience.members)
        return await self.repository.open_once(
            PollState(definition), targets, operation_key
        )

    async def record_answer(
        self,
        poll_id: UUID,
        choice: VoteChoice,
        source_event_id: UUID,
        received_at: datetime,
        context: TrustedCallbackContext,
    ) -> PollMutation:
        """Только callback/message handler вправе предоставить доверенный actor."""

        return await self.repository.record_answer_atomic(
            poll_id,
            context.house_id,
            context.actor_id,
            choice,
            source_event_id,
            received_at,
        )

    async def finalize(
        self, poll_id: UUID, context: TrustedHouseContext
    ) -> PollMutation:
        return await self.repository.finalize_atomic(
            poll_id, context.house_id, self.clock.now()
        )
