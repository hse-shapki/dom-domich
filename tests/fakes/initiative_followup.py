"""Fake outbox/решений для Z08 с блокировкой и частотным лимитом."""

import asyncio
from datetime import datetime
from uuid import UUID

from dom_domych.application.initiatives.followup import (
    InitiativeDecision,
    ReminderPolicy,
)
from dom_domych.domain.initiatives.models import InitiativeConflict
from dom_domych.domain.polls.models import PollState, PollStatus
from dom_domych.domain.polls.policy import InitiativeOutcome


class FakeCurrentRights:
    def __init__(self, allowed: set[UUID]) -> None:
        self.allowed = allowed

    async def filter_reachable(
        self, house_id: UUID, resident_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        return tuple(item for item in resident_ids if item in self.allowed)


class FakeFollowupRepository:
    def __init__(self, polls: dict[UUID, PollState]) -> None:
        self._lock = asyncio.Lock()
        self.polls = polls
        self.reminder_operations: dict[tuple[UUID, str], tuple[UUID, ...]] = {}
        self.reminder_history: dict[tuple[UUID, UUID], tuple[datetime, ...]] = {}
        self.outbox: list[tuple[UUID, UUID]] = []
        self.decisions: dict[UUID, InitiativeDecision] = {}
        self.decision_operations: dict[tuple[UUID, str], InitiativeDecision] = {}
        self.events: list[tuple[str, UUID]] = []

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
        async with self._lock:
            key = (house_id, operation_key)
            if key in self.reminder_operations:
                return self.reminder_operations[key]
            poll = self.polls[poll_id]
            if (
                poll.definition.house_id != house_id
                or poll.version != expected_poll_version
                or poll.status is not PollStatus.OPEN
                or now >= poll.definition.closes_at - policy.stop_before_deadline
            ):
                raise InitiativeConflict("poll changed while planning reminders")
            answered = {answer.resident_id for answer in poll.answers}
            planned: list[UUID] = []
            for resident_id in candidate_ids:
                if resident_id not in poll.definition.eligible_residents or resident_id in answered:
                    continue
                history_key = (poll_id, resident_id)
                history = self.reminder_history.get(history_key, ())
                if len(history) >= policy.max_per_resident:
                    continue
                if history and now - history[-1] < policy.min_interval:
                    continue
                self.reminder_history[history_key] = history + (now,)
                self.outbox.append((poll_id, resident_id))
                planned.append(resident_id)
            result = tuple(planned)
            self.reminder_operations[key] = result
            return result

    async def save_decision_once(
        self, decision: InitiativeDecision, operation_key: str
    ) -> InitiativeDecision:
        async with self._lock:
            poll = self.polls[decision.poll_id]
            if (
                poll.definition.house_id != decision.house_id
                or poll.definition.case_id != decision.case_id
                or poll.version != decision.poll_version
                or poll.status is not PollStatus.CLOSED
            ):
                raise InitiativeConflict("poll changed before decision commit")
            key = (decision.house_id, operation_key)
            existing = self.decision_operations.get(key)
            if existing is not None:
                if existing.poll_id != decision.poll_id or existing.outcome != decision.outcome:
                    raise InitiativeConflict("decision operation key conflict")
                return existing
            prior = self.decisions.get(decision.poll_id)
            if prior is not None:
                if prior.outcome != decision.outcome:
                    raise InitiativeConflict("initiative decision changed")
                return prior
            self.decisions[decision.poll_id] = decision
            self.decision_operations[key] = decision
            name = (
                "initiative.supported"
                if decision.outcome is InitiativeOutcome.SUPPORTED
                else "initiative.not_supported"
            )
            self.events.append((name, decision.case_id))
            return decision
