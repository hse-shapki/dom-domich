"""K06: вход сообщения из общего inbox в triage и agent coordinator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.agent.continuation import AgentCoordinator
from dom_domych.agent.runtime import AgentMode
from dom_domych.agent.triage import MessageKind, TriageService
from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
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


class MessageAgentHandler:
    """Строит trusted context до LLM и ставит ответ в outbox после сохранения run."""

    def __init__(
        self,
        principals: MessagePrincipalResolver,
        triage: TriageService,
        coordinator: AgentCoordinator,
        replies: MessageReplyPort,
    ) -> None:
        self.principals = principals
        self.triage = triage
        self.coordinator = coordinator
        self.replies = replies

    async def __call__(self, event: EventEnvelope) -> bool:
        if event.name is not EventName.MESSAGE_RECEIVED:
            return False
        if event.source is not EventSource.MAX or event.message is None:
            raise ValueError("UNTRUSTED_MESSAGE_EVENT")
        if event.actor_user_id != event.message.sender_user_id:
            raise ValueError("MESSAGE_ACTOR_MISMATCH")
        text = (event.message.text or "").strip()
        if not text:
            return False
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
        routes = await self.triage.route(text, context, at=event.received_at)
        if not routes:
            return True
        if all(route.kind is MessageKind.CONVERSATION for route in routes):
            return True
        route_facts = json.dumps(
            [route.model_dump(mode="json") for route in routes],
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
                {"role": "user", "content": text},
            ],
            context,
            AgentMode.TRIAGE,
            case_id=None,
            now=event.received_at,
        )
        if outcome.status != "completed":
            raise RuntimeError("AGENT_MESSAGE_FAILED")
        if outcome.text.strip():
            await self.replies.enqueue(event, principal, outcome.text.strip())
        return True


def register_message_agent(dispatcher: EventDispatcher, handler: MessageAgentHandler) -> None:
    """Вызывается после onboarding handler, который первым забирает `/start`."""

    dispatcher.register(EventName.MESSAGE_RECEIVED, handler)
