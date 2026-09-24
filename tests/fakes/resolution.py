"""Atomic fake case/poll/outbox для проверки результата Z12-Z13."""

import asyncio
from dataclasses import dataclass, replace
from uuid import UUID

from dom_domych.domain.polls.models import PollState
from dom_domych.domain.resolution.models import (
    ResolutionConflict,
    ResolutionState,
)


@dataclass(frozen=True)
class FakeResolutionCase:
    case_id: UUID
    house_id: UUID
    request_id: UUID
    original_audience_id: UUID
    version: int = 1
    workflow_status: str = "in_progress"


class FakeResolutionCasePort:
    def __init__(self, case: FakeResolutionCase) -> None:
        self.case = case

    async def get_for_resolution(
        self, case_id: UUID, house_id: UUID
    ) -> FakeResolutionCase:
        if case_id != self.case.case_id or house_id != self.case.house_id:
            raise ValueError("case not found in this house")
        return self.case


class FakeResolutionStore:
    def __init__(self, cases: FakeResolutionCasePort) -> None:
        self._lock = asyncio.Lock()
        self.cases = cases
        self.states: dict[UUID, ResolutionState] = {}
        self.polls: dict[UUID, PollState] = {}
        self.starts_by_key: dict[tuple[UUID, str], UUID] = {}
        self.starts_by_done_event: dict[tuple[UUID, UUID], UUID] = {}
        self.notifications: dict[UUID, tuple[UUID, ...]] = {}
        self.deadline_jobs: set[UUID] = set()
        self.events: list[tuple[str, UUID]] = []

    async def start_once(
        self,
        state: ResolutionState,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> ResolutionState:
        async with self._lock:
            key = (state.house_id, operation_key)
            done_key = (state.house_id, state.done_event_id)
            existing_id = self.starts_by_key.get(key) or self.starts_by_done_event.get(
                done_key
            )
            if existing_id is not None:
                existing = self.states[existing_id]
                if (
                    existing.case_id != state.case_id
                    or existing.request_id != state.request_id
                    or existing.original_audience_id != state.original_audience_id
                ):
                    raise ResolutionConflict("start operation key was reused")
                return existing
            case = self.cases.case
            if (
                case.case_id != state.case_id
                or case.house_id != state.house_id
                or case.version != state.case_version_at_start
                or case.workflow_status != "in_progress"
            ):
                raise ResolutionConflict("case changed before resolution start")
            self.states[state.check_id] = state
            self.polls[poll.definition.poll_id] = poll
            self.starts_by_key[key] = state.check_id
            self.starts_by_done_event[done_key] = state.check_id
            self.notifications[poll.definition.poll_id] = notification_targets
            self.deadline_jobs.add(poll.definition.poll_id)
            self.cases.case = replace(
                case, workflow_status="checking_resolution", version=case.version + 1
            )
            self.events.append(("resolution.started", state.case_id))
            return state
