"""Публичные карточки для MAX; персональные ответы не попадают в общий чат."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID

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
    lines = [
        f"Инициатива · редакция {revision.revision}",
        revision.wording,
        ProgressScale.build("Участие", progress.answered, progress.eligible).line(),
        ProgressScale.build("За от всех", progress.yes, progress.eligible).line(),
        ProgressScale.build(
            "За среди ответивших", progress.yes, progress.answered
        ).line(),
        (
            f"Порог участия: {policy.min_participation * 100}% · "
            f"поддержки среди ответивших: {policy.min_support_answered * 100}%"
        ),
    ]
    if progress.eligible == 0:
        lines.append("Подходящих жителей пока нет; позиция не определяется.")
    elif poll.status is PollStatus.OPEN:
        lines.append("Сбор позиций продолжается. Не ответил — не значит против.")
    elif poll.status is PollStatus.CANCELLED:
        lines.append("Опрос этой редакции отменён.")
    else:
        outcome = poll.outcome
        lines.append(
            f"Итог позиции: {_INITIATIVE_OUTCOMES[outcome] if isinstance(outcome, InitiativeOutcome) else 'не определён'}."
        )
    if policy.demo:
        lines.append("Демо-правило; не протокол ОСС и не юридический кворум.")
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
    lines = [
        f"Проблема: {title}",
        ProgressScale.build("Подтвердили", tally.yes, tally.eligible).line(),
        f"Подходящих жителей: {tally.eligible}. Недоставка ЛС не меняет это число.",
    ]
    if poll.status is PollStatus.OPEN:
        lines.append("Ожидаем подтверждения до срока опроса.")
    elif poll.status is PollStatus.CANCELLED:
        lines.append("Опрос отменён после изменения предмета обращения.")
    else:
        outcome = poll.outcome
        lines.append(
            f"Итог: {_PROBLEM_OUTCOMES[outcome] if isinstance(outcome, ProblemOutcome) else 'не определён'}."
        )
    if policy.demo:
        lines.append("Порог — демонстрационная настройка, не нормативное требование.")
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
        f"Обращение: {title}",
        f"Тестовая регистрация: {operation.registration_number or 'ожидается'}.",
        f"Статус тестового исполнителя: {_EXTERNAL_LABELS[operation.status]}.",
        f"Статус дела: {_WORKFLOW_LABELS.get(workflow_status, 'уточняется')}.",
    ]
    if operation.status is ExternalStatus.DONE:
        lines.append(
            "Исполнитель сообщил о выполнении. Результат должны проверить жители."
        )
    lines.append("ДЕМО: внешняя система и номер регистрации смоделированы.")
    return PublicCard(
        house_id=operation.draft.house_id,
        case_id=case_id,
        kind=CardKind.STATUS,
        text="\n".join(lines),
        edit_key=f"status:{case_id}",
        source_version=f"{operation.status.value}:{operation.status_updated_at}:{workflow_status}",
        demo=True,
    )
