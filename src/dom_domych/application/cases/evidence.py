"""K09: связывает проверенное входное вложение с делом без публичной отправки."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from dom_domych.agent.contracts import CaseView
from dom_domych.contracts.base import TrustedContext


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    case_id: UUID
    expected_version: int
    file_key: UUID | None
    operation_id: UUID


class EvidenceWriter(Protocol):
    async def add(
        self, command: EvidenceInput, context: TrustedContext, now: datetime
    ) -> CaseView: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class EvidenceService:
    """Вызывается только после проверки вложения ingress; source берёт из контекста."""

    def __init__(self, writer: EvidenceWriter, clock: Clock) -> None:
        self.writer = writer
        self.clock = clock

    async def add(self, command: EvidenceInput, context: TrustedContext) -> CaseView:
        if "evidence.write" not in context.capabilities or context.actor_id is None:
            raise PermissionError("FORBIDDEN")
        if command.expected_version < 1:
            raise ValueError("VERSION_CONFLICT")
        return await self.writer.add(command, context, self.clock.now())
