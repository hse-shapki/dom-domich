"""PostgreSQL adapters доверенного MAX actor/house и ответа agent в outbox."""

import re
from datetime import timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.contracts import CaseAttachMessage, CaseCreate, CaseKind, CaseSearch
from dom_domych.application.agent.messages import MessagePrincipal
from dom_domych.application.cases.service import CaseService
from dom_domych.contracts.base import ExecutionMode, TrustedContext
from dom_domych.contracts.events import EventEnvelope
from dom_domych.domain.ports.core import Clock, DeliveryIntent
from dom_domych.infrastructure.postgres.case_models import CaseMessageRow, CaseRow
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.models import (
    HouseRow,
    InboxEventRow,
    ResidencyRow,
    ResidentRow,
)


class PostgresMessagePrincipals:
    """Даёт capabilities только активному подтверждённому жителю выбранного дома."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        resident_capabilities: frozenset[str],
    ) -> None:
        self.sessions = sessions
        self.clock = clock
        self.resident_capabilities = resident_capabilities

    async def resolve(self, event: EventEnvelope) -> MessagePrincipal | None:
        if event.message is None:
            return None
        async with self.sessions() as session:
            resident = await session.scalar(
                select(ResidentRow).where(ResidentRow.max_user_id == event.message.sender_user_id)
            )
            if resident is None:
                return None
            house = await self._house(session, event.message.chat_id, resident)
            if house is None:
                return None
            now = self.clock.now()
            residency = await session.scalar(
                select(ResidencyRow.id).where(
                    ResidencyRow.house_id == house.id,
                    ResidencyRow.resident_id == resident.id,
                    ResidencyRow.confirmed.is_(True),
                    ResidencyRow.adult.is_(True),
                    ResidencyRow.valid_from <= now,
                    or_(ResidencyRow.valid_until.is_(None), ResidencyRow.valid_until > now),
                )
            )
            if residency is None:
                return None
            return MessagePrincipal(
                house_id=house.id,
                actor_id=resident.id,
                mode=ExecutionMode.DEMO if house.demo else ExecutionMode.LIVE,
                capabilities=self.resident_capabilities,
            )

    @staticmethod
    async def _house(session: AsyncSession, chat_id: str, resident: ResidentRow) -> HouseRow | None:
        if chat_id.startswith("dm:"):
            return (
                await session.get(HouseRow, resident.active_house_id)
                if resident.active_house_id is not None
                else None
            )
        return await session.scalar(select(HouseRow).where(HouseRow.max_chat_id == chat_id))


class PostgresMessageReplies:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def enqueue(self, event: EventEnvelope, principal: MessagePrincipal, text: str) -> UUID:
        if event.message is None:
            raise ValueError("MESSAGE_REQUIRED")
        direct = event.message.chat_id.startswith("dm:")
        buttons: tuple[tuple[str, str], ...] = ()
        async with self.sessions.begin() as session:
            case = (
                await session.execute(
                    select(CaseRow.id, CaseRow.title, CaseRow.status)
                    .join(
                        CaseMessageRow,
                        (CaseMessageRow.case_id == CaseRow.id)
                        & (CaseMessageRow.house_id == CaseRow.house_id),
                    )
                    .where(
                        CaseMessageRow.house_id == principal.house_id,
                        CaseMessageRow.message_id == event.event_id,
                        CaseMessageRow.actor_id == principal.actor_id,
                    )
                )
            ).one_or_none()
            if case is not None and case.status == "awaiting_confirmation":
                text = (
                    f"Я записал проблему «{case.title}». "
                    "Запустить опрос соседей, чтобы её подтвердить?"
                )
                direct = True
                buttons = (
                    ("Да, запустить", f"problem-confirm:{case.id}:yes"),
                    ("Нет", f"problem-confirm:{case.id}:no"),
                )
            elif any(
                marker in text.casefold()
                for marker in ("<think", "</think", "case.search", "case.create", "tool_call")
            ):
                text = (
                    "Я не смог разобраться в сообщении. Опишите проблему ещё раз обычными словами."
                )
                buttons = ()
            else:
                buttons = ()
            intent = DeliveryIntent(
                house_id=principal.house_id,
                operation_key=f"agent-reply:{event.event_id}",
                text=text,
                recipient_id=principal.actor_id if direct else None,
                chat_id=None if direct else event.message.chat_id,
                buttons=buttons,
            )
            return await PostgresDeliveryQueue(session, self.clock).enqueue(intent)


class PostgresMessageHistory:
    """Возвращает только недавний текст того же MAX actor и чата."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def previous_text(self, event: EventEnvelope, principal: MessagePrincipal) -> str | None:
        if event.message is None:
            return None
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(InboxEventRow)
                    .where(
                        InboxEventRow.source == "max",
                        InboxEventRow.event_name == "message.received",
                        or_(
                            InboxEventRow.house_id.is_(None),
                            InboxEventRow.house_id == principal.house_id,
                        ),
                        InboxEventRow.id != event.event_id,
                        InboxEventRow.received_at < event.received_at,
                        InboxEventRow.received_at >= event.received_at - timedelta(minutes=15),
                    )
                    .order_by(InboxEventRow.received_at.desc())
                    .limit(20)
                )
            ).all()
        for row in rows:
            payload = row.normalized_event or {}
            message = payload.get("message")
            if not isinstance(message, dict):
                continue
            if (
                payload.get("actor_user_id") != event.actor_user_id
                or message.get("chat_id") != event.message.chat_id
            ):
                continue
            text = message.get("text")
            if isinstance(text, str) and len(text.strip()) >= 8:
                return text.strip()
        return None


_ENTRANCE = re.compile(r"(?:в\s+)?(\d+)\s*(?:-?(?:й|ый|ой))?\s*подъезд", re.IGNORECASE)
_FLOOR = re.compile(r"(?:на\s+)?(\d+)\s*(?:-?(?:м|ом))?\s*этаж", re.IGNORECASE)
_ORDINALS = {
    "перв": 1,
    "втор": 2,
    "трет": 3,
    "четвер": 4,
    "пят": 5,
    "шест": 6,
    "седьм": 7,
    "восьм": 8,
    "девят": 9,
    "десят": 10,
}
_PROBLEM_TOPICS = (
    (re.compile(r"\b(?:свет\w*|освещ\w*|электр\w*|ламп\w*)\b", re.IGNORECASE), "lighting"),
    (re.compile(r"\b(?:лифт\w*)\b", re.IGNORECASE), "elevator"),
    (re.compile(r"\b(?:вод\w*|кран\w*|труб\w*|протеч\w*)\b", re.IGNORECASE), "water_supply"),
    (re.compile(r"\b(?:отоп\w*|батар\w*|радиатор\w*)\b", re.IGNORECASE), "heating"),
)


def _matched_problem_topics(text: str) -> tuple[str, ...]:
    return tuple(topic for pattern, topic in _PROBLEM_TOPICS if pattern.search(text))


def problem_topic(text: str) -> str | None:
    """Возвращает тему только для одной явно названной неисправности."""

    topics = _matched_problem_topics(text)
    return topics[0] if len(topics) == 1 else None


def _location_number(text: str, numeric: re.Pattern[str], noun: str) -> int | None:
    match = numeric.search(text)
    if match is not None:
        return int(match.group(1))
    folded = text.casefold()
    for stem, value in _ORDINALS.items():
        if re.search(rf"\b{stem}\w*\s+{noun}", folded):
            return value
    return None


class PostgresProblemDrafts:
    """Надёжный backend-path для очевидной обычной проблемы без второго LLM шага."""

    def __init__(self, cases: CaseService) -> None:
        self.cases = cases

    async def assess(self, text: str, event: EventEnvelope, context: TrustedContext) -> str:
        entrance = _location_number(text, _ENTRANCE, "подъезд")
        floor = _location_number(text, _FLOOR, "этаж")
        if floor is not None and entrance is None:
            return (
                "Не удалось безопасно определить место. Уточните номер подъезда; "
                "например: «5 подъезд»."
            )
        topics = _matched_problem_topics(text)
        if len(topics) > 1:
            return "Вы описали несколько неполадок. Напишите о каждой отдельно."
        if not topics:
            return "Уточните, пожалуйста, что именно не работает. Тогда я найду нужную службу."
        object_name = topics[0]
        candidates = await self.cases.search(
            CaseSearch(
                query=text[:500],
                entrance=entrance,
                floor=floor,
                object_name=object_name,
            ),
            context,
        )
        if candidates:
            candidate = candidates[0]
            await self.cases.attach_message(
                CaseAttachMessage(
                    case_id=candidate.case_id,
                    message_id=event.event_id,
                    expected_version=candidate.version,
                    operation_id=event.event_id,
                ),
                context,
            )
            return "Похожая проблема уже есть. Я добавил ваше сообщение к текущему опросу."
        title = text.replace("\nУточнение пользователя:", ";").strip()[:200]
        await self.cases.create(
            CaseCreate(
                kind=CaseKind.PROBLEM,
                title=title,
                description=text[:2000],
                entrance=entrance,
                floor=floor,
                object_name=object_name,
                source_message_id=event.event_id,
                candidate_case_ids=(),
                operation_id=event.event_id,
            ),
            context,
        )
        return "Проблема подготовлена. Подтвердите запуск опроса в личном чате."
