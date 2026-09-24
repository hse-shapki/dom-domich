"""Start/finish проверки результата с исходным составом жителей."""

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.domain.audiences.models import AudienceSnapshot
from dom_domych.domain.executor.models import DemoOperation, ExternalStatus
from dom_domych.domain.polls.models import PollDefinition, PollKind, PollState
from dom_domych.domain.polls.policy import ResolutionPolicy
from dom_domych.domain.resolution.models import (
    ResolutionConflict,
    ResolutionForbidden,
    ResolutionState,
)


class TrustedResolutionContext(Protocol):
    @property
    def house_id(self) -> UUID: ...

    @property
    def capabilities(self) -> frozenset[str]: ...


class ResolutionCase(Protocol):
    @property
    def case_id(self) -> UUID: ...

    @property
    def house_id(self) -> UUID: ...

    @property
    def request_id(self) -> UUID: ...

    @property
    def original_audience_id(self) -> UUID: ...

    @property
    def version(self) -> int: ...

    @property
    def workflow_status(self) -> str: ...


class ResolutionCasePort(Protocol):
    async def get_for_resolution(
        self, case_id: UUID, house_id: UUID
    ) -> ResolutionCase: ...


class ResolutionStore(Protocol):
    async def start_once(
        self,
        state: ResolutionState,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> ResolutionState:
        """В одной UoW: case checking, poll, outbox, deadline и done event key."""
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class ResolutionService:
    """Внешнее done открывает опрос, но не закрывает дело."""

    def __init__(
        self, cases: ResolutionCasePort, store: ResolutionStore, clock: Clock
    ) -> None:
        self.cases = cases
        self.store = store
        self.clock = clock

    async def start_check(
        self,
        case_id: UUID,
        operation: DemoOperation,
        done_event_id: UUID,
        original_audience: AudienceSnapshot,
        policy: ResolutionPolicy,
        window: timedelta,
        context: TrustedResolutionContext,
        *,
        operation_key: str,
    ) -> ResolutionState:
        self._require(context, "resolution.start_from_executor")
        case = await self.cases.get_for_resolution(case_id, context.house_id)
        if case.case_id != case_id or case.house_id != context.house_id:
            raise ResolutionForbidden("case belongs to another house")
        if (
            operation.draft.house_id != context.house_id
            or operation.draft.request_id != case.request_id
            or operation.status is not ExternalStatus.DONE
            or operation.registered_at is None
            or case.workflow_status not in {"in_progress", "checking_resolution"}
        ):
            raise ResolutionConflict("request is not a registered done for this case")
        if (
            original_audience.house_id != context.house_id
            or original_audience.audience_id != case.original_audience_id
        ):
            raise ResolutionForbidden("resolution must use original audience")
        if case.version <= 0 or window <= timedelta(0) or not operation_key:
            raise ValueError("case version, window and operation key are required")
        started_at = self.clock.now()
        state = ResolutionState(
            check_id=uuid4(),
            case_id=case_id,
            house_id=context.house_id,
            request_id=case.request_id,
            original_audience_id=case.original_audience_id,
            poll_id=uuid4(),
            case_version_at_start=case.version,
            done_event_id=done_event_id,
            started_at=started_at,
        )
        poll = PollState(
            PollDefinition(
                poll_id=state.poll_id,
                case_id=case_id,
                house_id=context.house_id,
                audience_id=original_audience.audience_id,
                kind=PollKind.RESOLUTION_CHECK,
                policy=policy,
                subject_revision=case.version,
                eligible_residents=frozenset(
                    item.resident_id for item in original_audience.members
                ),
                opens_at=started_at,
                closes_at=started_at + window,
            )
        )
        return await self.store.start_once(
            state,
            poll,
            tuple(item.resident_id for item in original_audience.members),
            operation_key,
        )

    @staticmethod
    def _require(context: TrustedResolutionContext, capability: str) -> None:
        if capability not in context.capabilities:
            raise ResolutionForbidden("resolution worker capability is required")
