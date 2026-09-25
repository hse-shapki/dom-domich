"""Коды ошибок для use cases, tools и transport mapping."""

from enum import StrEnum

from dom_domych.contracts.base import StrictContract


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    FORBIDDEN = "FORBIDDEN"
    WRONG_HOUSE = "WRONG_HOUSE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    NO_AUDIENCE = "NO_AUDIENCE"
    POLL_CLOSED = "POLL_CLOSED"
    STALE_REVISION = "STALE_REVISION"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    CANDIDATES_CHANGED = "CANDIDATES_CHANGED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    INVALID_STATE = "INVALID_STATE"
    DELIVERY_UNAVAILABLE = "DELIVERY_UNAVAILABLE"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    CONFLICT = "CONFLICT"


class ContractError(StrictContract):
    code: ErrorCode
    retryable: bool = False
    message: str | None = None
