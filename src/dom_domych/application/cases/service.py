"""K08: права и доверенный источник для команд создания/привязки дела."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from dom_domych.agent.contracts import (
    CaseAttachMessage,
    CaseCandidate,
    CaseCreate,
    CaseSearch,
    CaseView,
    TrustedContext,
)
from dom_domych.application.cases.candidates import CandidateService


class Clock(Protocol):
    def now(self) -> datetime: ...


class CaseWriter(Protocol):
    async def create_case(
        self, command: CaseCreate, context: TrustedContext, now: datetime
    ) -> CaseView: ...
    async def attach_message(
        self, command: CaseAttachMessage, context: TrustedContext, now: datetime
    ) -> CaseView: ...


class CaseService:
    """Никогда не использует house/actor/message source из аргументов модели."""

    def __init__(self, candidates: CandidateService, writer: CaseWriter, clock: Clock) -> None:
        self.candidates = candidates
        self.writer = writer
        self.clock = clock

    async def search(
        self, command: CaseSearch, context: TrustedContext
    ) -> tuple[CaseCandidate, ...]:
        return await self.candidates.search(command, context, at=self.clock.now())

    async def get(self, case_id: UUID, context: TrustedContext) -> CaseView | None:
        return await self.candidates.get(case_id, context)

    async def create(self, command: CaseCreate, context: TrustedContext) -> CaseView:
        self._require_write(context)
        if command.source_message_id != context.event_id:
            raise PermissionError("SOURCE_EVENT_MISMATCH")
        return await self.writer.create_case(command, context, self.clock.now())

    async def attach_message(self, command: CaseAttachMessage, context: TrustedContext) -> CaseView:
        self._require_write(context)
        if command.message_id != context.event_id:
            raise PermissionError("SOURCE_EVENT_MISMATCH")
        return await self.writer.attach_message(command, context, self.clock.now())

    @staticmethod
    def _require_write(context: TrustedContext) -> None:
        if "case.write" not in context.capabilities or context.actor_id is None:
            raise PermissionError("FORBIDDEN")
