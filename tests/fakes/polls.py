"""Транзакционный fake хранилища опросов для проверки доменной логики до PostgreSQL."""

import asyncio
from datetime import datetime
from uuid import UUID

from dom_domych.domain.polls.models import PollMutation, PollState, VoteChoice


class FakePollRepository:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.by_id: dict[UUID, PollState] = {}
        self.by_operation: dict[str, UUID] = {}
        self.notification_targets: dict[UUID, tuple[UUID, ...]] = {}
        self.deadlines: dict[UUID, datetime] = {}
        self.events: list[str] = []

    async def open_once(
        self,
        state: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> PollState:
        async with self.lock:
            previous_id = self.by_operation.get(operation_key)
            if previous_id is not None:
                previous = self.by_id[previous_id]
                if (
                    previous.definition.house_id != state.definition.house_id
                    or previous.definition.case_id != state.definition.case_id
                    or previous.definition.audience_id != state.definition.audience_id
                    or previous.definition.kind != state.definition.kind
                    or previous.definition.subject_revision
                    != state.definition.subject_revision
                    or previous.definition.policy != state.definition.policy
                    or previous.definition.eligible_residents
                    != state.definition.eligible_residents
                    or self.notification_targets[previous_id] != notification_targets
                ):
                    raise ValueError("operation key conflicts with another poll")
                return previous
            if any(
                item.definition.case_id == state.definition.case_id
                and item.definition.audience_id == state.definition.audience_id
                and item.definition.kind == state.definition.kind
                and item.definition.subject_revision
                == state.definition.subject_revision
                for item in self.by_id.values()
            ):
                raise ValueError("poll already opened for this subject revision")
            poll_id = state.definition.poll_id
            self.by_id[poll_id] = state
            self.by_operation[operation_key] = poll_id
            self.notification_targets[poll_id] = notification_targets
            self.deadlines[poll_id] = state.definition.closes_at
            return state

    async def record_answer_atomic(
        self,
        poll_id: UUID,
        house_id: UUID,
        actor_id: UUID,
        choice: VoteChoice,
        source_event_id: UUID,
        received_at: datetime,
    ) -> PollMutation:
        async with self.lock:
            current = self._get_scoped(poll_id, house_id)
            mutation = current.record_answer(
                actor_id, choice, source_event_id, received_at
            )
            if mutation.state != current:
                self.by_id[poll_id] = mutation.state
                self.events.extend(mutation.events)
            return mutation

    async def finalize_atomic(
        self, poll_id: UUID, house_id: UUID, now: datetime
    ) -> PollMutation:
        async with self.lock:
            current = self._get_scoped(poll_id, house_id)
            mutation = current.finalize(now)
            if mutation.state != current:
                self.by_id[poll_id] = mutation.state
                self.events.extend(mutation.events)
            return mutation

    def _get_scoped(self, poll_id: UUID, house_id: UUID) -> PollState:
        current = self.by_id.get(poll_id)
        if current is None or current.definition.house_id != house_id:
            raise ValueError("poll is missing or belongs to another house")
        return current
