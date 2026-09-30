"""Вопросы и явные команды не запускают скрытые мутации агента."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from dom_domych.agent.runtime import RunOutcome, ToolAudit
from dom_domych.agent.triage import MessageKind, RouteResult
from dom_domych.application.agent.messages import MessageAgentHandler, MessagePrincipal
from dom_domych.application.agent.resident_actions import ResidentActionHandler
from dom_domych.contracts.base import ExecutionMode
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource, MessagePayload

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


def _event(
    text: str, *, chat_id: str = "dm:42", attachment_refs: tuple[str, ...] = ()
) -> EventEnvelope:
    event_id = uuid4()
    return EventEnvelope(
        event_id=event_id,
        source=EventSource.MAX,
        source_key=f"message:{event_id}",
        name=EventName.MESSAGE_RECEIVED,
        occurred_at=NOW,
        received_at=NOW,
        correlation_id=event_id,
        actor_user_id="42",
        message=MessagePayload(
            chat_id=chat_id,
            message_id=str(event_id),
            sender_user_id="42",
            text=text,
            attachment_refs=attachment_refs,
        ),
    )


class Principals:
    def __init__(self) -> None:
        self.principal = MessagePrincipal(
            uuid4(), uuid4(), ExecutionMode.DEMO, frozenset({"case.read"})
        )

    async def resolve(self, event: EventEnvelope) -> MessagePrincipal:
        return self.principal


class Replies:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def enqueue(self, event: EventEnvelope, principal: MessagePrincipal, text: str):
        self.messages.append(text)
        return uuid4()


class Triage:
    def __init__(self, route: RouteResult) -> None:
        self.result = route
        self.texts: list[str] = []

    async def route(self, text, context, *, at):
        self.texts.append(text)
        return (self.result,)


class ForbiddenCoordinator:
    async def run_event(self, *args, **kwargs):
        raise AssertionError("question or clarification must not mutate a case")


class ValidationFailedCoordinator:
    async def run_event(self, *args, **kwargs):
        return RunOutcome(
            "failed",
            "",
            (ToolAudit("case.create", "VALIDATION_ERROR", None, ()),),
        )


class CompletedCoordinator:
    async def run_event(self, *args, **kwargs):
        return RunOutcome("completed", "Принято", ())


class History:
    async def previous_text(self, event, principal):
        return "Воды нет на третьем этаже"


class Actions:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, action, event, context):
        assert context.capabilities == frozenset({"case.read"})
        self.calls.append(action.name)
        return "Подтверждено"


@pytest.mark.asyncio
async def test_reviewed_question_answers_without_mutating_agent() -> None:
    replies = Replies()
    handler = MessageAgentHandler(
        Principals(),
        Triage(
            RouteResult(
                kind=MessageKind.QUESTION,
                text="Кто отвечает?",
                next_action="answer_with_sources",
                answer="Ответственный указан в правиле.",
                source_refs=("source:1",),
            )
        ),
        ForbiddenCoordinator(),
        replies,
    )
    assert await handler(_event("Кто отвечает за свет?"))
    assert replies.messages == [
        "Ответственный указан в правиле.\nИсточник: проверенный документ дома"
    ]


@pytest.mark.asyncio
async def test_unreviewed_question_asks_for_clarification() -> None:
    replies = Replies()
    handler = MessageAgentHandler(
        Principals(),
        Triage(
            RouteResult(
                kind=MessageKind.QUESTION,
                text="Кто отвечает?",
                next_action="ask_clarification",
            )
        ),
        ForbiddenCoordinator(),
        replies,
    )
    assert await handler(_event("Кто отвечает?"))
    assert "Уточните" in replies.messages[0]


@pytest.mark.asyncio
async def test_private_greeting_gets_reply_without_mutating_agent() -> None:
    replies = Replies()
    handler = MessageAgentHandler(
        Principals(),
        Triage(
            RouteResult(
                kind=MessageKind.CONVERSATION,
                text="Привет",
                next_action="none",
            )
        ),
        ForbiddenCoordinator(),
        replies,
    )
    assert await handler(_event("Привет"))
    assert replies.messages and "Расскажите о проблеме" in replies.messages[0]
    assert await handler(_event("Привет", chat_id="group"))
    assert len(replies.messages) == 1


@pytest.mark.asyncio
async def test_attachment_without_command_gets_actionable_reply() -> None:
    replies = Replies()
    handler = MessageAgentHandler(
        Principals(),
        Triage(
            RouteResult(
                kind=MessageKind.CONVERSATION,
                text="unused",
                next_action="none",
            )
        ),
        ForbiddenCoordinator(),
        replies,
    )
    event = _event("", attachment_refs=("image",))

    assert await handler(event)
    assert replies.messages and "/evidence ID_ДЕЛА" in replies.messages[0]


@pytest.mark.asyncio
async def test_invalid_case_location_gets_actionable_reply_instead_of_silence() -> None:
    replies = Replies()
    handler = MessageAgentHandler(
        Principals(),
        Triage(
            RouteResult(
                kind=MessageKind.PROBLEM,
                text="Не горит свет на пятом этаже",
                next_action="problem.assess",
            )
        ),
        ValidationFailedCoordinator(),
        replies,
    )

    assert await handler(_event("Не горит свет на пятом этаже"))
    assert replies.messages == [
        "Не удалось безопасно определить место. Уточните: весь дом или номер подъезда; "
        "если указываете этаж — обязательно укажите подъезд."
    ]


@pytest.mark.asyncio
async def test_short_scope_reply_continues_previous_group_problem() -> None:
    replies = Replies()
    triage = Triage(
        RouteResult(
            kind=MessageKind.PROBLEM,
            text="Воды нет на третьем этаже в пятом подъезде",
            next_action="problem.assess",
        )
    )
    handler = MessageAgentHandler(Principals(), triage, CompletedCoordinator(), replies, History())

    assert await handler(_event("5 подъезд", chat_id="group"))
    assert triage.texts == ["Воды нет на третьем этаже\nУточнение пользователя: 5 подъезд"]
    assert replies.messages == ["Принято"]


@pytest.mark.asyncio
async def test_mutating_command_requires_private_chat_and_exact_shape() -> None:
    replies, actions = Replies(), Actions()
    handler = ResidentActionHandler(Principals(), replies, actions)
    case_id = uuid4()
    assert await handler(_event(f"/prepare {case_id}", chat_id="group"))
    assert not actions.calls
    assert await handler(_event("/prepare invalid"))
    assert not actions.calls
    assert await handler(_event(f"/prepare {case_id}"))
    assert actions.calls == ["prepare"]
    assert replies.messages[-1] == "Подтверждено"
