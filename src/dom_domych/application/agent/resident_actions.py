"""Явные команды жителя из MAX для действий, которым нужно его согласие."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.application.agent.messages import MessagePrincipalResolver, MessageReplyPort
from dom_domych.contracts.base import PrincipalType, TrustedContext
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.initiatives.models import InitiativeError


@dataclass(frozen=True, slots=True)
class ResidentAction:
    name: str
    entity_id: UUID | None
    expected_revision: int | None = None
    wording: str | None = None
    evidence_id: UUID | None = None
    assessment: str | None = None


class ResidentActionPort(Protocol):
    async def execute(
        self, action: ResidentAction, event: EventEnvelope, context: TrustedContext
    ) -> str: ...


_USAGE = (
    "Команды в личном чате: /confirm; /prepare ID_ДЕЛА; /approve ID_ОБРАЩЕНИЯ; "
    "/send ID_ОБРАЩЕНИЯ; /revise ID_ДЕЛА РЕДАКЦИЯ НОВЫЙ_ТЕКСТ; "
    "/evidence ID_ДЕЛА с одним фото; /assess ID_ДЕЛА ID_ФОТО accepted|rejected."
)


def parse_resident_action(text: str) -> ResidentAction | None:
    """Команда распознаётся только по целому первому слову, UUID обязателен."""

    parts = text.strip().split(maxsplit=3)
    if len(parts) == 1 and parts[0].casefold() in {"да", "/confirm"}:
        return ResidentAction("confirm", None)
    if not parts or parts[0].casefold() not in {
        "/prepare",
        "/approve",
        "/send",
        "/revise",
        "/evidence",
        "/assess",
        "/confirm",
    }:
        return None
    name = parts[0].casefold()[1:]
    if len(parts) < 2:
        raise ValueError("INVALID_ACTION")
    try:
        entity_id = UUID(parts[1])
    except ValueError as exc:
        raise ValueError("INVALID_ACTION") from exc
    if name == "revise":
        if len(parts) != 4 or not parts[2].isdecimal():
            raise ValueError("INVALID_ACTION")
        revision = int(parts[2])
        if revision < 1 or len(parts[3].strip()) < 10 or len(parts[3]) > 4000:
            raise ValueError("INVALID_ACTION")
        return ResidentAction(name, entity_id, revision, parts[3].strip())
    if name == "assess":
        if len(parts) != 4 or parts[3] not in {"accepted", "rejected"}:
            raise ValueError("INVALID_ACTION")
        try:
            evidence_id = UUID(parts[2])
        except ValueError as exc:
            raise ValueError("INVALID_ACTION") from exc
        return ResidentAction(name, entity_id, evidence_id=evidence_id, assessment=parts[3])
    if len(parts) != 2:
        raise ValueError("INVALID_ACTION")
    return ResidentAction(name, entity_id)


class ResidentActionHandler:
    """Доверенный MAX actor вызывает use case; текст команды не даёт прав LLM."""

    def __init__(
        self,
        principals: MessagePrincipalResolver,
        replies: MessageReplyPort,
        actions: ResidentActionPort,
    ) -> None:
        self.principals = principals
        self.replies = replies
        self.actions = actions

    async def __call__(self, event: EventEnvelope) -> bool:
        if event.name is not EventName.MESSAGE_RECEIVED or event.message is None:
            return False
        if (
            event.source is not EventSource.MAX
            or event.actor_user_id != event.message.sender_user_id
        ):
            raise ValueError("UNTRUSTED_MESSAGE_EVENT")
        text = (event.message.text or "").strip()
        try:
            action = parse_resident_action(text)
        except ValueError:
            action = None
            if text.split(maxsplit=1)[0].casefold() not in {
                "/prepare",
                "/approve",
                "/send",
                "/revise",
                "/evidence",
                "/assess",
                "/confirm",
            }:
                return False
            principal = await self.principals.resolve(event)
            if principal is not None:
                await self.replies.enqueue(event, principal, _USAGE)
            return True
        if action is None:
            return False
        principal = await self.principals.resolve(event)
        if principal is None:
            return False
        if event.house_id is not None and event.house_id != principal.house_id:
            raise ValueError("MESSAGE_HOUSE_MISMATCH")
        if not event.message.chat_id.startswith("dm:"):
            await self.replies.enqueue(
                event,
                principal,
                "Для согласования, отправки и вложений напишите мне в личном чате.",
            )
            return True
        if action.name == "evidence" and event.message.attachment_refs.count("image") != 1:
            await self.replies.enqueue(event, principal, "Добавьте к команде ровно одно фото.")
            return True
        context = TrustedContext(
            run_id=uuid4(),
            event_id=event.event_id,
            house_id=principal.house_id,
            actor_id=principal.actor_id,
            principal_type=PrincipalType.RESIDENT,
            capabilities=principal.capabilities,
            correlation_id=event.correlation_id,
            mode=principal.mode,
        )
        try:
            result = await self.actions.execute(action, event, context)
        except (PermissionError, ValueError, InitiativeError):
            result = "Действие не выполнено: проверьте ID, актуальную версию и свои права."
        await self.replies.enqueue(event, principal, result)
        return True
