from uuid import UUID, uuid4

import pytest

from dom_domych.application.notifications.text import enqueue_text, split_max_text
from dom_domych.domain.ports.core import DeliveryIntent


class FakeDelivery:
    def __init__(self) -> None:
        self.intents: list[DeliveryIntent] = []

    async def enqueue(self, intent: DeliveryIntent) -> UUID:
        self.intents.append(intent)
        return uuid4()


def test_split_max_text_preserves_content_and_limits_chunks() -> None:
    text = ("абзац " * 800) + "конец"
    chunks = split_max_text(text)

    assert "".join(chunks) == text
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 4000 for chunk in chunks)


def test_split_max_text_does_not_exceed_limit_when_boundary_is_at_edge() -> None:
    text = ("x" * 3999) + " " + "tail"

    chunks = split_max_text(text)

    assert "".join(chunks) == text
    assert tuple(map(len, chunks)) == (4000, 4)


@pytest.mark.asyncio
async def test_enqueue_text_uses_stable_operation_keys_in_one_uow() -> None:
    delivery = FakeDelivery()
    intent = DeliveryIntent(uuid4(), "notice", "слово " * 1000, chat_id="123")

    result = await enqueue_text(delivery, intent)

    assert len(result) == len(delivery.intents) > 1
    assert [item.operation_key for item in delivery.intents] == [
        f"notice:part:{index:03}" for index in range(1, len(result) + 1)
    ]
