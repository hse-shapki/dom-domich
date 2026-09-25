"""Результат типизированного tool; успех создаётся только после handler."""

from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from dom_domych.contracts.base import StrictContract
from dom_domych.contracts.errors import ContractError


class ToolResult(StrictContract):
    ok: bool
    data: dict[str, JsonValue] | None = None
    error: ContractError | None = None
    entity_version: int | None = Field(default=None, ge=1)
    source_refs: tuple[str, ...] = ()
    operation_id: UUID | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "ToolResult":
        if self.ok and self.error is not None:
            raise ValueError("successful tool cannot contain error")
        if not self.ok and self.error is None:
            raise ValueError("failed tool requires error")
        return self
