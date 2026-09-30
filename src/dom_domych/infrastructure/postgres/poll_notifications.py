"""Адресное приглашение в опрос в транзакции его открытия."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.application.cards.builders import human_poll_deadline
from dom_domych.application.polls.callback import StoredPollAction
from dom_domych.domain.polls.models import PollDefinition, PollKind, VoteChoice
from dom_domych.domain.ports.core import DeliveryIntent
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore


@dataclass(frozen=True)
class _OpeningClock:
    at: datetime

    def now(self) -> datetime:
        return self.at


async def enqueue_poll_invitations(session: AsyncSession, definition: PollDefinition) -> None:
    """Вызывается только после нового insert poll; повтор команды не выпускает токены."""
    if definition.kind is PollKind.RESOLUTION_CHECK:
        # ResolutionStore формирует собственное приглашение о выполнении.
        return
    title = await session.scalar(
        select(CaseRow.title).where(
            CaseRow.id == definition.case_id, CaseRow.house_id == definition.house_id
        )
    )
    if title is None:
        raise ValueError("poll case is missing")
    labels = (
        ("Да, подтверждаю", "Нет, не подтверждаю")
        if definition.kind is PollKind.PROBLEM_CONFIRMATION
        else ("Поддерживаю", "Не поддерживаю")
    )
    prompt = (
        "Подтвердите, что эта проблема действительно есть."
        if definition.kind is PollKind.PROBLEM_CONFIRMATION
        else "Поддерживаете эту инициативу?"
    )
    for resident_id in sorted(definition.eligible_residents):
        buttons: list[tuple[str, str]] = []
        for label, choice in zip(labels, (VoteChoice.YES, VoteChoice.NO), strict=True):
            token = await PostgresPollActionStore(session).create(
                StoredPollAction(
                    poll_id=definition.poll_id,
                    house_id=definition.house_id,
                    audience_id=definition.audience_id,
                    subject_revision=definition.subject_revision,
                    choice=choice,
                    expires_at=definition.closes_at,
                    bound_resident_id=resident_id,
                )
            )
            buttons.append((label, token))
        await PostgresDeliveryQueue(session, _OpeningClock(definition.opens_at)).enqueue(
            DeliveryIntent(
                house_id=definition.house_id,
                operation_key=f"poll:invite:{definition.poll_id}:{resident_id}",
                text=(
                    f"🏠 {title}\n\n"
                    f"{prompt}\n"
                    f"Ответить можно до {human_poll_deadline(definition.closes_at)}.\n"
                    "Ваш ответ увидите только вы. В группе появится общий итог без имён."
                    + ("\nℹ️ Это тестовый опрос." if definition.policy.demo else "")
                ),
                recipient_id=resident_id,
                buttons=tuple(buttons),
            )
        )
