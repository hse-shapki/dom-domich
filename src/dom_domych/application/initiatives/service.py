"""Создание и изменение инициативы вместе с новой ревизией опроса."""

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.domain.audiences.models import AudienceSnapshot
from dom_domych.domain.initiatives.models import (
    InitiativeConflict,
    InitiativeForbidden,
    InitiativeRevision,
    InitiativeState,
)
from dom_domych.domain.polls.models import PollDefinition, PollKind, PollState
from dom_domych.domain.polls.policy import InitiativePolicy


class TrustedInitiativeContext(Protocol):
    @property
    def house_id(self) -> UUID: ...

    @property
    def actor_id(self) -> UUID: ...


class CaseReference(Protocol):
    @property
    def case_id(self) -> UUID: ...

    @property
    def house_id(self) -> UUID: ...

    @property
    def author_id(self) -> UUID: ...

    @property
    def kind(self) -> str: ...

    @property
    def version(self) -> int: ...


class CasePort(Protocol):
    async def get_case(self, case_id: UUID, house_id: UUID) -> CaseReference: ...


class InitiativeRepository(Protocol):
    async def get(self, case_id: UUID, house_id: UUID) -> InitiativeState: ...

    async def get_operation_result(
        self, house_id: UUID, operation_key: str
    ) -> InitiativeState | None: ...

    async def create_and_open_atomic(
        self,
        state: InitiativeState,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> InitiativeState:
        """В одной UoW сохраняет инициативу, опрос, outbox и deadline."""
        ...

    async def revise_and_replace_poll_atomic(
        self,
        previous: InitiativeState,
        updated: InitiativeState,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> InitiativeState:
        """Старый poll отменён, action tokens отозваны, новый poll открыт в одной UoW."""
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class InitiativeService:
    """LLM задаёт текст/область; права, версию и опрос проверяет backend."""

    def __init__(self, cases: CasePort, repository: InitiativeRepository, clock: Clock) -> None:
        self.cases = cases
        self.repository = repository
        self.clock = clock

    async def create(
        self,
        case_id: UUID,
        wording: str,
        audience: AudienceSnapshot,
        policy: InitiativePolicy,
        window: timedelta,
        context: TrustedInitiativeContext,
        *,
        operation_key: str,
    ) -> InitiativeState:
        case = await self._case_for_author(case_id, context)
        self._validate(audience, context, wording, window, operation_key)
        previous_result = await self.repository.get_operation_result(
            context.house_id, operation_key
        )
        if previous_result is not None:
            if (
                previous_result.case_id != case_id
                or previous_result.revisions[0].wording != wording.strip()
                or previous_result.revisions[0].audience_id != audience.audience_id
            ):
                raise InitiativeConflict("operation key was used for another initiative")
            return previous_result
        revision = InitiativeRevision(
            1, wording.strip(), audience.audience_id, uuid4(), self.clock.now()
        )
        state = InitiativeState(
            case_id, context.house_id, context.actor_id, case.version, (revision,)
        )
        poll = self._new_poll(state, audience, policy, window)
        return await self.repository.create_and_open_atomic(
            state,
            poll,
            tuple(item.resident_id for item in audience.members),
            operation_key,
        )

    async def revise(
        self,
        case_id: UUID,
        wording: str,
        audience: AudienceSnapshot,
        policy: InitiativePolicy,
        window: timedelta,
        context: TrustedInitiativeContext,
        *,
        expected_revision: int,
        operation_key: str,
    ) -> InitiativeState:
        case = await self._case_for_author(case_id, context)
        self._validate(audience, context, wording, window, operation_key)
        previous_result = await self.repository.get_operation_result(
            context.house_id, operation_key
        )
        if previous_result is not None:
            if (
                previous_result.case_id != case_id
                or previous_result.current.revision != expected_revision + 1
                or previous_result.current.wording != wording.strip()
                or previous_result.current.audience_id != audience.audience_id
            ):
                raise InitiativeConflict("operation key was used for another revision")
            return previous_result
        previous = await self.repository.get(case_id, context.house_id)
        if previous.author_id != context.actor_id or previous.case_version != case.version:
            raise InitiativeConflict("case or author changed")
        revision = InitiativeRevision(
            expected_revision + 1,
            wording.strip(),
            audience.audience_id,
            uuid4(),
            self.clock.now(),
        )
        updated = previous.revise(revision, expected_revision)
        poll = self._new_poll(updated, audience, policy, window)
        return await self.repository.revise_and_replace_poll_atomic(
            previous,
            updated,
            poll,
            tuple(item.resident_id for item in audience.members),
            operation_key,
        )

    async def _case_for_author(
        self, case_id: UUID, context: TrustedInitiativeContext
    ) -> CaseReference:
        case = await self.cases.get_case(case_id, context.house_id)
        if case.case_id != case_id or case.house_id != context.house_id:
            raise InitiativeForbidden("case belongs to another house")
        if case.kind != "initiative" or case.author_id != context.actor_id:
            raise InitiativeForbidden("only initiative author may change wording")
        if case.version <= 0:
            raise InitiativeConflict("invalid case version")
        return case

    @staticmethod
    def _validate(
        audience: AudienceSnapshot,
        context: TrustedInitiativeContext,
        wording: str,
        window: timedelta,
        operation_key: str,
    ) -> None:
        if audience.house_id != context.house_id:
            raise InitiativeForbidden("audience belongs to another house")
        if audience.eligible_count == 0:
            raise ValueError("initiative audience cannot be empty")
        if not wording.strip() or len(wording) > 4_000:
            raise ValueError("initiative wording is empty or too long")
        if window <= timedelta(0) or not operation_key:
            raise ValueError("poll window and operation key are required")

    @staticmethod
    def _new_poll(
        state: InitiativeState,
        audience: AudienceSnapshot,
        policy: InitiativePolicy,
        window: timedelta,
    ) -> PollState:
        revision = state.current
        return PollState(
            PollDefinition(
                poll_id=revision.poll_id,
                case_id=state.case_id,
                house_id=state.house_id,
                audience_id=audience.audience_id,
                kind=PollKind.INITIATIVE_POSITION,
                policy=policy,
                subject_revision=revision.revision,
                eligible_residents=frozenset(item.resident_id for item in audience.members),
                opens_at=revision.created_at,
                closes_at=revision.created_at + window,
            )
        )
