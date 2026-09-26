"""K07: подготовка кандидатов без автоматического слияния дел."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

import structlog

from dom_domych.agent.contracts import CaseCandidate, CaseSearch, CaseView, TrustedContext
from dom_domych.domain.knowledge.ports import EmbeddingPort

logger = structlog.get_logger()


class CaseReader(Protocol):
    async def search_candidates(
        self,
        command: CaseSearch,
        house_id: UUID,
        at: datetime,
        embedding: tuple[float, ...] | None,
        embedding_revision: str | None,
    ) -> tuple[CaseCandidate, ...]: ...
    async def get_case(self, case_id: UUID, house_id: UUID) -> CaseView | None: ...


class CandidateService:
    """Возвращает факты кандидатов; решение attach/create принимает CaseService."""

    def __init__(self, reader: CaseReader, embeddings: EmbeddingPort | None = None) -> None:
        self.reader = reader
        self.embeddings = embeddings

    async def search(
        self, command: CaseSearch, context: TrustedContext, *, at: datetime
    ) -> tuple[CaseCandidate, ...]:
        if "case.read" not in context.capabilities:
            raise PermissionError("FORBIDDEN")
        vector = None
        if self.embeddings is not None:
            try:
                vector = await self.embeddings.embed(command.query)
            except (TimeoutError, ConnectionError) as exc:
                logger.warning("case_embedding_unavailable", error=type(exc).__name__)
        return await self.reader.search_candidates(
            command,
            context.house_id,
            at,
            vector,
            self.embeddings.revision if vector is not None and self.embeddings else None,
        )

    async def get(self, case_id: UUID, context: TrustedContext) -> CaseView | None:
        if "case.read" not in context.capabilities:
            raise PermissionError("FORBIDDEN")
        return await self.reader.get_case(case_id, context.house_id)
