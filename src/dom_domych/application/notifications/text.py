"""Подготовка длинного текста MAX до транзакционного enqueue всех частей."""

from dataclasses import replace
from uuid import UUID

from dom_domych.domain.ports.core import DeliveryIntent, DeliveryPort

MAX_TEXT_LENGTH = 4000


def split_max_text(text: str, limit: int = MAX_TEXT_LENGTH) -> tuple[str, ...]:
    if limit < 1:
        raise ValueError("text limit must be positive")
    if not text:
        return ()
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        boundary = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if boundary < limit // 2:
            boundary = limit
        else:
            boundary += 1
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
    if remaining:
        chunks.append(remaining)
    return tuple(chunks)


async def enqueue_text(port: DeliveryPort, intent: DeliveryIntent) -> tuple[UUID, ...]:
    """Сохраняет все части в текущей UoW; commit остаётся ответственностью вызывающего."""

    chunks = split_max_text(intent.text)
    if len(chunks) <= 1:
        return (await port.enqueue(intent),)
    if intent.edit_key is not None or intent.file_key is not None:
        raise ValueError("long edited/file delivery must be rendered as a shorter card")
    results: list[UUID] = []
    for index, chunk in enumerate(chunks, 1):
        results.append(
            await port.enqueue(
                replace(
                    intent,
                    operation_key=f"{intent.operation_key}:part:{index:03}",
                    text=chunk,
                )
            )
        )
    return tuple(results)
