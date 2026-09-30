"""Validation helpers for MAX identifiers crossing application boundaries."""


def parse_max_chat_id(value: str) -> int | None:
    """Parse a MAX dialog/group identifier represented as a signed int64 string."""

    digits = value[1:] if value.startswith("-") else value
    if not digits.isdecimal():
        return None
    parsed = int(value)
    return parsed if -(2**63) <= parsed <= 2**63 - 1 else None


def valid_max_chat_id(value: str) -> bool:
    """Return whether value can be passed to MAX as a chat identifier."""

    return parse_max_chat_id(value) is not None
