"""Чистые правила трёх видов опросов; интеграция хранения и MAX находится вне домена."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from math import ceil


class ProblemOutcome(StrEnum):
    NO_AUDIENCE = "no_audience"
    COLLECTING = "collecting"
    REQUEST_READY = "request_ready"
    NEED_EVIDENCE = "need_evidence"


class InitiativeOutcome(StrEnum):
    NO_AUDIENCE = "no_audience"
    COLLECTING = "collecting"
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"


class ResolutionOutcome(StrEnum):
    CHECKING = "checking"
    CLOSED = "closed"
    REOPENED = "reopened"
    UNCONFIRMED = "resolution_unconfirmed"


def _check_ratio(value: Decimal, name: str, *, allow_zero: bool = False) -> None:
    lower_ok = value >= 0 if allow_zero else value > 0
    if not value.is_finite() or not lower_ok or value > 1:
        raise ValueError(
            f"{name} must be {'between 0 and 1' if allow_zero else 'in (0, 1]'}"
        )


def _required(eligible: int, ratio: Decimal) -> int:
    return ceil(Decimal(eligible) * ratio)


@dataclass(frozen=True, slots=True)
class VoteTally:
    """Снимок явных уникальных ответов; молчание и недоставка в ответы не входят."""

    eligible: int
    yes: int
    no: int

    def __post_init__(self) -> None:
        if (
            min(self.eligible, self.yes, self.no) < 0
            or self.yes + self.no > self.eligible
        ):
            raise ValueError("invalid vote tally")

    @property
    def answered(self) -> int:
        return self.yes + self.no


@dataclass(frozen=True, slots=True)
class ProblemPolicy:
    """Версия правила подтверждения; доля 20% существует только в demo-конфигурации."""

    revision: str
    threshold_ratio: Decimal
    wait_period: timedelta
    demo: bool

    def __post_init__(self) -> None:
        if not self.revision or self.wait_period <= timedelta(0):
            raise ValueError("revision and positive wait period are required")
        _check_ratio(self.threshold_ratio, "threshold_ratio")


@dataclass(frozen=True, slots=True)
class InitiativePolicy:
    """Участие и поддержка разделены; правило не является кворумом ОСС."""

    revision: str
    min_participation: Decimal
    min_support_answered: Decimal
    demo: bool

    def __post_init__(self) -> None:
        if not self.revision:
            raise ValueError("revision is required")
        _check_ratio(self.min_participation, "min_participation")
        _check_ratio(self.min_support_answered, "min_support_answered")


@dataclass(frozen=True, slots=True)
class ResolutionPolicy:
    """Отрицательный итог имеет приоритет над закрытием после финализации опроса."""

    revision: str
    min_response_ratio: Decimal
    min_yes_answered: Decimal
    reopen_no_ratio: Decimal
    demo: bool

    def __post_init__(self) -> None:
        if not self.revision:
            raise ValueError("revision is required")
        _check_ratio(self.min_response_ratio, "min_response_ratio")
        _check_ratio(self.min_yes_answered, "min_yes_answered")
        _check_ratio(self.reopen_no_ratio, "reopen_no_ratio", allow_zero=True)


@dataclass(frozen=True, slots=True)
class InitiativeProgress:
    eligible: int
    answered: int
    yes: int
    participation: Decimal | None
    support_total: Decimal | None
    support_answered: Decimal | None


def demo_problem_policy() -> ProblemPolicy:
    """Пример 20% из журнала решений и обязательные пять часов ожидания."""

    return ProblemPolicy(
        revision="demo-problem-v1",
        threshold_ratio=Decimal("0.20"),
        wait_period=timedelta(hours=5),
        demo=True,
    )


def demo_initiative_policy() -> InitiativePolicy:
    """Временные пороги демо: 50% участия и 60% «за» среди ответивших."""

    return InitiativePolicy(
        revision="demo-initiative-v1",
        min_participation=Decimal("0.50"),
        min_support_answered=Decimal("0.60"),
        demo=True,
    )


def demo_resolution_policy() -> ResolutionPolicy:
    """Временные пороги из инженерной спецификации; это не нормативное правило."""

    return ResolutionPolicy(
        revision="demo-resolution-v1",
        min_response_ratio=Decimal("0.50"),
        min_yes_answered=Decimal("0.80"),
        reopen_no_ratio=Decimal("0.20"),
        demo=True,
    )


def evaluate_problem(
    tally: VoteTally, policy: ProblemPolicy, *, expired: bool
) -> ProblemOutcome:
    """Порог считается от всей зафиксированной категории, а не от доставленных ЛС."""

    if tally.eligible == 0:
        return ProblemOutcome.NO_AUDIENCE
    if tally.yes >= _required(tally.eligible, policy.threshold_ratio):
        return ProblemOutcome.REQUEST_READY
    if expired:
        return ProblemOutcome.NEED_EVIDENCE
    return ProblemOutcome.COLLECTING


def initiative_progress(tally: VoteTally) -> InitiativeProgress:
    """Отдаёт отдельные шкалы участия и поддержки; отсутствие знаменателя — None."""

    eligible = Decimal(tally.eligible)
    answered = Decimal(tally.answered)
    return InitiativeProgress(
        eligible=tally.eligible,
        answered=tally.answered,
        yes=tally.yes,
        participation=answered / eligible if tally.eligible else None,
        support_total=Decimal(tally.yes) / eligible if tally.eligible else None,
        support_answered=Decimal(tally.yes) / answered if tally.answered else None,
    )


def evaluate_initiative(
    tally: VoteTally, policy: InitiativePolicy, *, finalized: bool
) -> InitiativeOutcome:
    """Итог позиции жителей вычисляется только из зафиксированной версии правил."""

    if tally.eligible == 0:
        return InitiativeOutcome.NO_AUDIENCE
    if not finalized:
        return InitiativeOutcome.COLLECTING
    if tally.answered < _required(tally.eligible, policy.min_participation):
        return InitiativeOutcome.NOT_SUPPORTED
    support = Decimal(tally.yes) / Decimal(tally.answered)
    if support >= policy.min_support_answered:
        return InitiativeOutcome.SUPPORTED
    return InitiativeOutcome.NOT_SUPPORTED


def evaluate_resolution(
    tally: VoteTally, policy: ResolutionPolicy, *, finalized: bool
) -> ResolutionOutcome:
    """Исполнительское done не влияет на результат до отдельного опроса жителей."""

    if not finalized:
        return ResolutionOutcome.CHECKING
    if tally.eligible == 0 or tally.answered == 0:
        return ResolutionOutcome.UNCONFIRMED
    answered = Decimal(tally.answered)
    if Decimal(tally.no) / answered > policy.reopen_no_ratio:
        return ResolutionOutcome.REOPENED
    if tally.answered < _required(tally.eligible, policy.min_response_ratio):
        return ResolutionOutcome.UNCONFIRMED
    if Decimal(tally.yes) / answered >= policy.min_yes_answered:
        return ResolutionOutcome.CLOSED
    return ResolutionOutcome.UNCONFIRMED


def received_during_poll(
    received_at: datetime, opens_at: datetime, closes_at: datetime
) -> bool:
    """Сравнивает время надёжного приёма ingress, а не время обработки worker."""

    if any(
        value.tzinfo is None or value.utcoffset() is None
        for value in (received_at, opens_at, closes_at)
    ):
        raise ValueError("poll timestamps must be timezone-aware")
    if closes_at <= opens_at:
        raise ValueError("closes_at must be later than opens_at")
    return opens_at <= received_at < closes_at
