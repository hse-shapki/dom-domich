"""Atomic fake для связки initiative revision + poll replacement."""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from dom_domych.domain.initiatives.models import InitiativeConflict, InitiativeState
from dom_domych.domain.polls.models import PollState


@dataclass(frozen=True)
class FakeCase:
    case_id: UUID
    house_id: UUID
    author_id: UUID
    kind: str = "initiative"
    version: int = 1


class FakeCasePort:
    def __init__(self, case: FakeCase) -> None:
        self.case = case

    async def get_case(self, case_id: UUID, house_id: UUID) -> FakeCase:
        if case_id != self.case.case_id or house_id != self.case.house_id:
            raise ValueError("case not found in this house")
        return self.case


class FakeInitiativeRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.states: dict[UUID, InitiativeState] = {}
        self.polls: dict[UUID, PollState] = {}
        self.operation_results: dict[tuple[UUID, str], InitiativeState] = {}
        self.revoked_poll_ids: set[UUID] = set()
        self.notifications: dict[UUID, tuple[UUID, ...]] = {}
        self.events: list[tuple[str, UUID]] = []

    async def get(self, case_id: UUID, house_id: UUID) -> InitiativeState:
        state = self.states.get(case_id)
        if state is None or state.house_id != house_id:
            raise ValueError("initiative not found in this house")
        return state

    async def get_operation_result(
        self, house_id: UUID, operation_key: str
    ) -> InitiativeState | None:
        return self.operation_results.get((house_id, operation_key))

    async def create_and_open_atomic(
        self,
        state: InitiativeState,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> InitiativeState:
        async with self._lock:
            key = (state.house_id, operation_key)
            existing = self.operation_results.get(key)
            if existing is not None:
                if (
                    existing.case_id != state.case_id
                    or existing.current.wording != state.current.wording
                    or existing.current.audience_id != state.current.audience_id
                ):
                    raise InitiativeConflict(
                        "operation key was used for another initiative"
                    )
                return existing
            if state.case_id in self.states:
                raise InitiativeConflict("initiative already exists")
            self.states[state.case_id] = state
            self.polls[poll.definition.poll_id] = poll
            self.operation_results[key] = state
            self.notifications[poll.definition.poll_id] = notification_targets
            self.events.append(("initiative.created", state.case_id))
            return state

    async def revise_and_replace_poll_atomic(
        self,
        previous: InitiativeState,
        updated: InitiativeState,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> InitiativeState:
        async with self._lock:
            key = (updated.house_id, operation_key)
            existing = self.operation_results.get(key)
            if existing is not None:
                if (
                    existing.case_id != updated.case_id
                    or existing.current.wording != updated.current.wording
                    or existing.current.audience_id != updated.current.audience_id
                    or existing.current.revision != updated.current.revision
                ):
                    raise InitiativeConflict(
                        "operation key was used for another revision"
                    )
                return existing
            if self.states.get(updated.case_id) != previous:
                raise InitiativeConflict("initiative revision changed concurrently")
            old_poll_id = previous.current.poll_id
            cancellation = self.polls[old_poll_id].cancel()
            self.polls[old_poll_id] = cancellation.state
            self.revoked_poll_ids.add(old_poll_id)
            self.states[updated.case_id] = updated
            self.polls[poll.definition.poll_id] = poll
            self.operation_results[key] = updated
            self.notifications[poll.definition.poll_id] = notification_targets
            self.events.append(("initiative.revised", updated.case_id))
            return updated
