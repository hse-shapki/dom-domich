"""Приём разрешённых источников и консервативный поиск знаний."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

import structlog

from dom_domych.agent.contracts import KnowledgeHit, KnowledgeSearch, TrustedContext
from dom_domych.domain.knowledge.models import RuleVersion, SourceRevision
from dom_domych.domain.knowledge.ports import EmbeddingPort

logger = structlog.get_logger()


class KnowledgeRepository(Protocol):
    async def add_source(
        self,
        source: SourceRevision,
        chunks: tuple[str, ...],
        embeddings: tuple[tuple[float, ...], ...] | None,
        embedding_revision: str | None,
    ) -> None: ...
    async def review_source(
        self, source_id: UUID, revision: int, house_id: UUID | None
    ) -> bool: ...
    async def add_rule(self, rule: RuleVersion) -> None: ...
    async def search(
        self,
        query: str,
        topic: str | None,
        house_id: UUID,
        at: datetime,
        limit: int,
        embedding: tuple[float, ...] | None,
        embedding_revision: str | None,
    ) -> tuple[KnowledgeHit, ...]: ...
    async def find_rule(self, topic: str, house_id: UUID, at: datetime) -> RuleVersion | None: ...


def split_chunks(text: str, *, max_chars: int = 900) -> tuple[str, ...]:
    """Делит текст на ограниченные части, не теряя длинные абзацы."""
    if max_chars < 100:
        raise ValueError("Слишком малый chunk")
    words = text.split()
    if not words:
        raise ValueError("Пустой источник")
    chunks: list[str] = []
    current = ""
    for word in words:
        if len(word) > max_chars:
            raise ValueError("Слишком длинное слово в источнике")
        proposed = f"{current} {word}" if current else word
        if len(proposed) > max_chars:
            chunks.append(current)
            current = word
        else:
            current = proposed
    if current:
        chunks.append(current)
    return tuple(chunks)


class KnowledgeService:
    """Источники проходят явную проверку; поиск возвращает только проверенные версии."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        allowed_hosts: frozenset[str],
        embeddings: EmbeddingPort | None = None,
    ) -> None:
        self.repository = repository
        self.allowed_hosts = allowed_hosts
        self.embeddings = embeddings

    async def ingest(self, source: SourceRevision, context: TrustedContext) -> None:
        self._require_manage(context, source.house_id)
        if source.reviewed or source.revision < 1 or not source.title.strip():
            raise ValueError("Источник должен поступить непроверенной новой версией")
        parsed = urlparse(source.uri)
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_hosts:
            raise ValueError("Источник не входит в список разрешённых HTTPS-хостов")
        if source.valid_from and source.valid_until and source.valid_until <= source.valid_from:
            raise ValueError("Неверный интервал действия источника")
        chunks = split_chunks(source.text)
        vectors: tuple[tuple[float, ...], ...] | None = None
        if self.embeddings is not None:
            try:
                vectors = tuple([await self.embeddings.embed(chunk) for chunk in chunks])
            except (TimeoutError, ConnectionError) as exc:
                logger.warning("knowledge_embedding_unavailable", error=type(exc).__name__)
        await self.repository.add_source(
            source,
            chunks,
            vectors,
            self.embeddings.revision if vectors is not None and self.embeddings else None,
        )

    async def review(
        self, source_id: UUID, revision: int, house_id: UUID | None, context: TrustedContext
    ) -> bool:
        self._require_manage(context, house_id)
        return await self.repository.review_source(source_id, revision, house_id)

    async def add_rule(self, rule: RuleVersion, context: TrustedContext) -> None:
        self._require_manage(context, rule.house_id)
        await self.repository.add_rule(rule)

    async def search(
        self, command: KnowledgeSearch, context: TrustedContext, *, at: datetime
    ) -> tuple[KnowledgeHit, ...]:
        if "knowledge.read" not in context.capabilities:
            raise PermissionError("FORBIDDEN")
        vector = None
        if self.embeddings is not None:
            try:
                vector = await self.embeddings.embed(command.query)
            except (TimeoutError, ConnectionError) as exc:
                logger.warning("knowledge_embedding_unavailable", error=type(exc).__name__)
        return await self.repository.search(
            command.query,
            command.topic,
            context.house_id,
            at,
            5,
            vector,
            self.embeddings.revision if vector is not None and self.embeddings else None,
        )

    async def applicable_rule(
        self, topic: str, context: TrustedContext, *, at: datetime
    ) -> RuleVersion | None:
        if "knowledge.read" not in context.capabilities:
            raise PermissionError("FORBIDDEN")
        return await self.repository.find_rule(topic, context.house_id, at)

    @staticmethod
    def _require_manage(context: TrustedContext, house_id: UUID | None) -> None:
        if "knowledge.manage" not in context.capabilities:
            raise PermissionError("FORBIDDEN")
        if house_id is None and "knowledge.global.manage" not in context.capabilities:
            raise PermissionError("FORBIDDEN")
        if house_id is not None and house_id != context.house_id:
            raise PermissionError("FORBIDDEN")
