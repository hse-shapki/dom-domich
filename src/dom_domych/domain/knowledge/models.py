"""Знания не становятся нормативом без проверки источника и применимости."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SourceRevision:
    source_id: UUID
    revision: int
    house_id: UUID | None
    title: str
    uri: str
    text: str
    reviewed: bool
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def is_applicable(self, house_id: UUID, at: datetime) -> bool:
        return (
            self.reviewed
            and self.house_id in (None, house_id)
            and (self.valid_from is None or self.valid_from <= at)
            and (self.valid_until is None or at < self.valid_until)
        )


@dataclass(frozen=True, slots=True)
class RuleVersion:
    rule_id: UUID
    source_id: UUID
    source_revision: int
    house_id: UUID | None
    topic: str
    responsible_id: UUID
    deadline: timedelta | None
    deadline_origin: str | None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        if self.deadline is not None and (
            self.deadline <= timedelta(0) or self.deadline_origin is None
        ):
            raise ValueError("Срок требует положительной длительности и точки отсчёта")

    def is_applicable(self, house_id: UUID, topic: str, at: datetime) -> bool:
        return (
            self.house_id in (None, house_id)
            and self.topic == topic
            and (self.valid_from is None or self.valid_from <= at)
            and (self.valid_until is None or at < self.valid_until)
        )
