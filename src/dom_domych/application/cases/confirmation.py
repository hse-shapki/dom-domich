"""Кнопки явного согласия автора на запуск problem workflow."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.max.client import MaxApiClient, MaxApiError
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseMessageRow, CaseRow
from dom_domych.infrastructure.postgres.inbox import save_domain_event
from dom_domych.infrastructure.postgres.models import ResidencyRow, ResidentRow

logger = structlog.get_logger()
_PREFIX = "problem-confirm:"


class PostgresProblemConfirmationCallbacks:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        max_client: MaxApiClient,
        clock: Clock,
    ) -> None:
        self.sessions = sessions
        self.max_client = max_client
        self.clock = clock

    async def handle(self, event: EventEnvelope) -> bool:
        callback = event.callback
        if (
            event.source is not EventSource.MAX
            or event.name is not EventName.CALLBACK_RECEIVED
            or callback is None
            or callback.sender_user_id != event.actor_user_id
            or not callback.action_token.startswith(_PREFIX)
        ):
            return False
        try:
            _, case_raw, choice = callback.action_token.split(":", 2)
            case_id = UUID(case_raw)
            if choice not in {"yes", "no"}:
                raise ValueError
        except ValueError:
            await self._ack(event, "Кнопка устарела. Создайте обращение заново.")
            return True

        message = await self._apply(event, case_id, choice)
        await self._ack(event, message)
        return True

    async def _apply(self, event: EventEnvelope, case_id: UUID, choice: str) -> str:
        assert event.callback is not None
        now = self.clock.now()
        async with self.sessions.begin() as session:
            found = (
                await session.execute(
                    select(CaseRow, CaseMessageRow.actor_id)
                    .join(
                        CaseMessageRow,
                        (CaseMessageRow.case_id == CaseRow.id)
                        & (CaseMessageRow.house_id == CaseRow.house_id),
                    )
                    .join(ResidentRow, ResidentRow.id == CaseMessageRow.actor_id)
                    .join(
                        ResidencyRow,
                        (ResidencyRow.resident_id == ResidentRow.id)
                        & (ResidencyRow.house_id == CaseRow.house_id),
                    )
                    .where(
                        CaseRow.id == case_id,
                        CaseRow.kind == "problem",
                        CaseMessageRow.relation == "origin",
                        ResidentRow.max_user_id == event.callback.sender_user_id,
                        ResidencyRow.confirmed.is_(True),
                        ResidencyRow.adult.is_(True),
                        ResidencyRow.valid_from <= event.received_at,
                        or_(
                            ResidencyRow.valid_until.is_(None),
                            ResidencyRow.valid_until > event.received_at,
                        ),
                    )
                    .limit(1)
                    .with_for_update(of=CaseRow)
                )
            ).first()
            if found is None:
                return "Эта кнопка недоступна для вашего профиля."
            case, actor_id = found
            if case.status != "awaiting_confirmation":
                return (
                    "Опрос уже запускается или завершён."
                    if choice == "yes"
                    else "Решение уже было принято."
                )
            previous_version = case.version
            case.version += 1
            event_type = "problem.confirmed" if choice == "yes" else "problem.cancelled"
            case.status = "detected" if choice == "yes" else "closed"
            if choice == "no":
                case.closed_at = now
            session.add(
                CaseEventRow(
                    id=uuid4(),
                    case_id=case.id,
                    house_id=case.house_id,
                    event_type=event_type,
                    before_version=previous_version,
                    after_version=case.version,
                    actor_id=actor_id,
                    source_message_id=None,
                    operation_id=event.event_id,
                    occurred_at=now,
                    facts={"choice": choice},
                )
            )
            if choice == "yes":
                domain_event_id = uuid4()
                await save_domain_event(
                    session,
                    EventEnvelope(
                        event_id=domain_event_id,
                        source=EventSource.DOMAIN,
                        source_key=f"problem-detected:{case.id}",
                        name=EventName.PROBLEM_DETECTED,
                        occurred_at=now,
                        received_at=now,
                        correlation_id=event.correlation_id,
                        house_id=case.house_id,
                        entity=EntityEventPayload(
                            entity_id=case.id,
                            entity_version=case.version,
                            case_id=case.id,
                            causation_id=event.event_id,
                        ),
                    ),
                )
        return (
            "Запускаю опрос в группе."
            if choice == "yes"
            else "Понял. Буду рад помочь в следующий раз."
        )

    async def _ack(self, event: EventEnvelope, message: str) -> None:
        assert event.callback is not None
        try:
            await self.max_client.answer_callback(
                event.callback.callback_id,
                message,
                dialog_key=event.callback.chat_id or f"user:{event.callback.sender_user_id}",
            )
        except (MaxApiError, httpx.TransportError) as exc:
            logger.warning("problem_confirmation_ack_failed", error=type(exc).__name__)


def register_problem_confirmation_callbacks(
    dispatcher: EventDispatcher, processor: PostgresProblemConfirmationCallbacks
) -> None:
    dispatcher.register(EventName.CALLBACK_RECEIVED, processor.handle)
