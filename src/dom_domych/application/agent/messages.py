"""K06: вход сообщения из общего inbox в triage и agent coordinator."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.agent.continuation import AgentCoordinator
from dom_domych.agent.runtime import AgentMode
from dom_domych.agent.triage import MessageKind, TriageService
from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.contracts.errors import ErrorCode
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource


@dataclass(frozen=True, slots=True)
class MessagePrincipal:
    house_id: UUID
    actor_id: UUID
    mode: ExecutionMode
    capabilities: frozenset[str]


class MessagePrincipalResolver(Protocol):
    async def resolve(self, event: EventEnvelope) -> MessagePrincipal | None: ...


class MessageReplyPort(Protocol):
    async def enqueue(
        self, event: EventEnvelope, principal: MessagePrincipal, text: str
    ) -> UUID: ...


class MessageHistoryPort(Protocol):
    async def previous_text(
        self, event: EventEnvelope, principal: MessagePrincipal
    ) -> str | None: ...


class ProblemDraftPort(Protocol):
    async def assess(self, text: str, event: EventEnvelope, context: TrustedContext) -> str: ...


_SHORT_SCOPE_REPLY = re.compile(
    r"^(?:в\s+)?(?:весь\s+дом|по\s+всему\s+дому|(?:подъезд\s*)?\d+\s*"
    r"(?:-?(?:й|ый|ой))?\s*(?:подъезд(?:е|а)?|п\.?)?)[.!]?$",
    re.IGNORECASE,
)
_OBVIOUS_PROBLEM = re.compile(
    r"(?:нет\s+воды|не\s+горит|не\s+работает|сломал|протеч|теч[её]т|"
    r"нет\s+света|холодн|не\s+греет|застрял\s+лифт)",
    re.IGNORECASE,
)
_OBVIOUS_EMERGENCY = re.compile(
    r"(?:пахнет\s+газом|утечка\s+газа|искрит|горит\s+щиток|прорвало\s+трубу)",
    re.IGNORECASE,
)


class MessageAgentHandler:
    """Строит trusted context до LLM и ставит ответ в outbox после сохранения run."""

    def __init__(
        self,
        principals: MessagePrincipalResolver,
        triage: TriageService,
        coordinator: AgentCoordinator,
        replies: MessageReplyPort,
        history: MessageHistoryPort | None = None,
        problem_drafts: ProblemDraftPort | None = None,
    ) -> None:
        self.principals = principals
        self.triage = triage
        self.coordinator = coordinator
        self.replies = replies
        self.history = history
        self.problem_drafts = problem_drafts

    async def __call__(self, event: EventEnvelope) -> bool:
        if event.name is not EventName.MESSAGE_RECEIVED:
            return False
        if event.source is not EventSource.MAX or event.message is None:
            raise ValueError("UNTRUSTED_MESSAGE_EVENT")
        if event.actor_user_id != event.message.sender_user_id:
            raise ValueError("MESSAGE_ACTOR_MISMATCH")
        text = (event.message.text or "").strip()
        if not text:
            principal = await self.principals.resolve(event)
            if principal is None:
                return False
            reply = (
                "Вложение без команды не обработано. Для фото по делу отправьте в личном "
                "чате /evidence ID_ДЕЛА и прикрепите ровно одно фото."
                if event.message.attachment_refs
                else "Сообщение без текста не обработано. Опишите проблему словами."
            )
            await self.replies.enqueue(event, principal, reply)
            return True
        principal = await self.principals.resolve(event)
        if principal is None:
            return False
        if event.house_id is not None and event.house_id != principal.house_id:
            raise ValueError("MESSAGE_HOUSE_MISMATCH")
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
        model_text = text
        if self.history is not None and _SHORT_SCOPE_REPLY.fullmatch(text):
            previous = await self.history.previous_text(event, principal)
            if previous is not None:
                model_text = f"{previous}\nУточнение пользователя: {text}"
        if (
            self.problem_drafts is not None
            and _OBVIOUS_PROBLEM.search(model_text)
            and not _OBVIOUS_EMERGENCY.search(model_text)
        ):
            reply = await self.problem_drafts.assess(model_text, event, context)
            await self.replies.enqueue(event, principal, reply)
            return True
        routes = await self.triage.route(model_text, context, at=event.received_at)
        if not routes:
            return True
        if all(route.kind is MessageKind.CONVERSATION for route in routes):
            if event.message.chat_id.startswith("dm:"):
                await self.replies.enqueue(
                    event,
                    principal,
                    "Здравствуйте! Расскажите о проблеме дома, задайте вопрос "
                    "или предложите инициативу.",
                )
            return True
        answers = [
            (
                f"{route.answer}\nИсточник: {', '.join(route.source_refs)}"
                if route.next_action == "answer_with_sources" and route.answer
                else (
                    "Уточните, пожалуйста, вопрос или место: "
                    "в проверенных источниках дома пока нет ответа."
                )
            )
            for route in routes
            if route.kind is MessageKind.QUESTION
        ]
        actions = [
            route
            for route in routes
            if route.kind not in {MessageKind.QUESTION, MessageKind.CONVERSATION}
        ]
        if not actions:
            if answers:
                await self.replies.enqueue(event, principal, "\n\n".join(answers))
            return True
        route_facts = json.dumps(
            [route.model_dump(mode="json") for route in actions],
            ensure_ascii=False,
            sort_keys=True,
        )
        outcome = await self.coordinator.run_event(
            [
                {
                    "role": "system",
                    "content": (
                        "Типизированный triage уже выполнен backend. Следуй маршрутам, "
                        "не объявляй регистрацию или выполнение без результата tool. "
                        f"Маршруты: {route_facts}"
                    ),
                },
                {"role": "user", "content": model_text},
            ],
            context,
            AgentMode.TRIAGE,
            case_id=None,
            now=event.received_at,
        )
        if outcome.status != "completed":
            if any(item.outcome == ErrorCode.VALIDATION_ERROR.value for item in outcome.audit):
                await self.replies.enqueue(
                    event,
                    principal,
                    "Не удалось безопасно определить место. Уточните: весь дом или номер "
                    "подъезда; если указываете этаж — обязательно укажите подъезд.",
                )
                return True
            raise RuntimeError("AGENT_MESSAGE_FAILED")
        reply = "\n\n".join([*answers, outcome.text.strip()]).strip()
        if reply:
            await self.replies.enqueue(event, principal, reply)
        return True


def register_message_agent(dispatcher: EventDispatcher, handler: MessageAgentHandler) -> None:
    """Вызывается после onboarding handler, который первым забирает `/start`."""

    dispatcher.register(EventName.MESSAGE_RECEIVED, handler)
