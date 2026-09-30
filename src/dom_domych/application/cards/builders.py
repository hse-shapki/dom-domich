"""Публичные карточки для MAX; персональные ответы не попадают в общий чат."""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from math import ceil
from uuid import UUID
from zoneinfo import ZoneInfo

from dom_domych.domain.executor.models import DemoOperation, ExternalStatus
from dom_domych.domain.initiatives.models import InitiativeState
from dom_domych.domain.polls.models import PollKind, PollState, PollStatus
from dom_domych.domain.polls.policy import (
    InitiativeOutcome,
    InitiativePolicy,
    ProblemOutcome,
    ProblemPolicy,
    initiative_progress,
)

_INITIATIVE_OUTCOMES = {
    InitiativeOutcome.COLLECTING: "сбор позиций",
    InitiativeOutcome.SUPPORTED: "поддержана по правилу опроса",
    InitiativeOutcome.NOT_SUPPORTED: "поддержки недостаточно",
    InitiativeOutcome.NO_AUDIENCE: "нет подходящих жителей",
}
_PROBLEM_OUTCOMES = {
    ProblemOutcome.COLLECTING: "сбор подтверждений",
    ProblemOutcome.REQUEST_READY: "обращение можно подготовить",
    ProblemOutcome.NEED_EVIDENCE: "требуются дополнительные доказательства",
    ProblemOutcome.NO_AUDIENCE: "нет подходящих жителей",
}
_EXTERNAL_LABELS = {
    ExternalStatus.SUBMITTED: "направлено тестовому исполнителю",
    ExternalStatus.REGISTERED: "зарегистрировано тестовым исполнителем",
    ExternalStatus.IN_PROGRESS: "в работе у тестового исполнителя",
    ExternalStatus.DONE: "исполнитель отметил выполнение",
}
_WORKFLOW_LABELS = {
    "awaiting_registration": "ожидает регистрации",
    "in_progress": "в работе",
    "checking_resolution": "жители проверяют результат",
    "closed": "закрыто после проверки",
    "reopened": "возвращено в работу",
    "resolution_unconfirmed": "результат не подтверждён",
}


class CardKind(StrEnum):
    INITIATIVE = "initiative"
    PROBLEM = "problem"
    STATUS = "status"


@dataclass(frozen=True, slots=True)
class ProgressScale:
    label: str
    numerator: int
    denominator: int
    percentage: str
    bar: str

    @classmethod
    def build(cls, label: str, numerator: int, denominator: int) -> "ProgressScale":
        if numerator < 0 or denominator < 0 or numerator > denominator:
            raise ValueError("progress scale has invalid values")
        if denominator == 0:
            return cls(label, numerator, denominator, "—", "░" * 10)
        ratio = Decimal(numerator) / Decimal(denominator)
        percent = (ratio * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        filled = min(10, int((ratio * 10).quantize(Decimal(1), rounding=ROUND_HALF_UP)))
        return cls(
            label,
            numerator,
            denominator,
            str(percent).replace(".", ",") + "%",
            "█" * filled + "░" * (10 - filled),
        )

    def line(self) -> str:
        return f"{self.label}: {self.numerator}/{self.denominator} ({self.percentage}) {self.bar}"


@dataclass(frozen=True, slots=True)
class PublicCard:
    house_id: UUID
    case_id: UUID
    kind: CardKind
    text: str
    edit_key: str
    source_version: str
    demo: bool


_RU_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def human_poll_deadline(value: datetime) -> str:
    local = value.astimezone(ZoneInfo("Europe/Moscow"))
    return f"{local.day} {_RU_MONTHS[local.month - 1]} в {local:%H:%M} по Москве"


def _votes_word(count: int) -> str:
    if count % 100 in range(11, 15):
        return "подтверждений"
    return {1: "подтверждение", 2: "подтверждения", 3: "подтверждения", 4: "подтверждения"}.get(
        count % 10, "подтверждений"
    )


def initiative_card(state: InitiativeState, poll: PollState) -> PublicCard:
    """Показывает три знаменателя отдельно; исходные resident IDs не используются."""

    revision = state.current
    definition = poll.definition
    if (
        definition.kind is not PollKind.INITIATIVE_POSITION
        or definition.case_id != state.case_id
        or definition.house_id != state.house_id
        or definition.poll_id != revision.poll_id
        or definition.audience_id != revision.audience_id
        or definition.subject_revision != revision.revision
    ):
        raise ValueError("poll does not match current initiative revision")
    policy = definition.policy
    if not isinstance(policy, InitiativePolicy):
        raise TypeError("initiative card needs initiative policy")
    progress = initiative_progress(poll.tally)
    participation = format((policy.min_participation * 100).normalize(), "f").replace(".", ",")
    support = format((policy.min_support_answered * 100).normalize(), "f").replace(".", ",")
    lines = [
        f"🏠 Предложение соседей · версия {revision.revision}",
        revision.wording,
        ProgressScale.build("Ответили", progress.answered, progress.eligible).line(),
        ProgressScale.build("Поддержали", progress.yes, progress.eligible).line(),
        ProgressScale.build("Из ответивших поддержали", progress.yes, progress.answered).line(),
        (
            f"Для положительного итога нужны ответы от {participation}% "
            f"жителей и поддержка {support}% ответивших."
        ),
    ]
    if progress.eligible == 0:
        lines.append("Подходящих жителей пока нет; позиция не определяется.")
    elif poll.status is PollStatus.OPEN:
        lines.extend(
            (
                "Опрос продолжается. Если человек не ответил, это не голос против.",
                f"Ответить можно до {human_poll_deadline(definition.closes_at)}.",
            )
        )
    elif poll.status is PollStatus.CANCELLED:
        lines.append("Опрос этой редакции отменён.")
    else:
        outcome = poll.outcome
        label = (
            _INITIATIVE_OUTCOMES[outcome]
            if isinstance(outcome, InitiativeOutcome)
            else "не определён"
        )
        lines.append(f"Итог: {label}.")
    if policy.demo:
        lines.append("ℹ️ Это тестовый опрос, не решение общего собрания собственников.")
    return PublicCard(
        house_id=state.house_id,
        case_id=state.case_id,
        kind=CardKind.INITIATIVE,
        text="\n".join(lines),
        edit_key=f"initiative:{state.case_id}",
        source_version=f"{revision.revision}:{poll.version}",
        demo=policy.demo,
    )


def problem_card(title: str, poll: PollState) -> PublicCard:
    definition = poll.definition
    if definition.kind is not PollKind.PROBLEM_CONFIRMATION:
        raise ValueError("problem card needs problem poll")
    policy = definition.policy
    if not isinstance(policy, ProblemPolicy):
        raise TypeError("problem card needs problem policy")
    tally = poll.tally
    progress = ProgressScale.build("Подтвердили", tally.yes, tally.eligible)
    required = ceil(Decimal(tally.eligible) * policy.threshold_ratio)
    lines = [
        f"🏠 Проверяем проблему: {title}",
        "",
        f"Подтвердили {tally.yes} из {tally.eligible} жителей ({progress.percentage})",
        progress.bar,
    ]
    if poll.status is PollStatus.OPEN:
        remaining = max(0, required - tally.yes)
        lines.extend(
            [
                (
                    "Подтверждений достаточно. Можно готовить обращение."
                    if remaining == 0
                    else f"Для обращения нужно ещё {remaining} {_votes_word(remaining)}."
                ),
                f"Ответить можно до {human_poll_deadline(definition.closes_at)}.",
                "Ответьте кнопкой здесь или в личном сообщении от бота.",
            ]
        )
    elif poll.status is PollStatus.CANCELLED:
        lines.append("Опрос отменён после изменения предмета обращения.")
    else:
        outcome = poll.outcome
        label = (
            _PROBLEM_OUTCOMES[outcome] if isinstance(outcome, ProblemOutcome) else "не определён"
        )
        lines.append(f"Итог: {label}.")
    if policy.demo:
        lines.append("ℹ️ Это тестовый опрос. Порог задан для демонстрации.")
    return PublicCard(
        house_id=definition.house_id,
        case_id=definition.case_id,
        kind=CardKind.PROBLEM,
        text="\n".join(lines),
        edit_key=f"problem:{definition.case_id}",
        source_version=str(poll.version),
        demo=policy.demo,
    )


def status_card(
    title: str, operation: DemoOperation, workflow_status: str, case_id: UUID
) -> PublicCard:
    if not workflow_status:
        raise ValueError("workflow status is required")
    lines = [
        f"🏠 Заявка: {title}",
        f"Номер: {operation.registration_number or 'ждём регистрации'}.",
        f"Исполнитель: {_EXTERNAL_LABELS[operation.status]}.",
        f"Сейчас: {_WORKFLOW_LABELS.get(workflow_status, 'уточняется')}.",
    ]
    if operation.status is ExternalStatus.DONE:
        lines.append("Исполнитель сообщил о выполнении. Результат должны проверить жители.")
    lines.append("ℹ️ Это тестовая заявка и тестовый номер регистрации.")
    return PublicCard(
        house_id=operation.draft.house_id,
        case_id=case_id,
        kind=CardKind.STATUS,
        text="\n".join(lines),
        edit_key=f"status:{case_id}",
        source_version=f"{operation.status.value}:{operation.status_updated_at}:{workflow_status}",
        demo=True,
    )
