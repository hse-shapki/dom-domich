"""K00 fake handlers: граница model JSON и общих A01 ToolResult/TrustedContext."""

from __future__ import annotations

from pydantic import ValidationError

from dom_domych.agent.contracts import (
    TOOL_INPUTS,
    CaseAttachMessage,
    CaseCreate,
    CaseGet,
    CasePort,
    CaseSearch,
    KnowledgePort,
    KnowledgeSearch,
    RequestGetStatus,
    RequestPort,
    RequestPrepare,
    RequestSubmit,
)
from dom_domych.contracts.base import TrustedContext
from dom_domych.contracts.errors import ContractError, ErrorCode
from dom_domych.contracts.tools import ToolResult

_CAPABILITIES = {
    "case.search": "case.read",
    "case.get": "case.read",
    "case.create": "case.write",
    "case.attach_message": "case.write",
    "knowledge.search": "knowledge.read",
    "request.prepare": "request.write",
    "request.submit": "request.submit",
    "request.get_status": "request.read",
}


def _error(code: ErrorCode) -> ToolResult:
    return ToolResult(ok=False, error=ContractError(code=code))


class KToolHandlers:
    """Проверяет схему и права до обращения к port; house/actor не берёт из JSON."""

    def __init__(self, cases: CasePort, knowledge: KnowledgePort, requests: RequestPort) -> None:
        self.cases = cases
        self.knowledge = knowledge
        self.requests = requests

    async def execute(self, name: str, arguments_json: str, context: TrustedContext) -> ToolResult:
        model = TOOL_INPUTS.get(name)
        if model is None:
            return _error(ErrorCode.FORBIDDEN)
        if _CAPABILITIES[name] not in context.capabilities:
            return _error(ErrorCode.FORBIDDEN)
        if name in {"case.create", "case.attach_message", "request.prepare", "request.submit"}:
            if context.actor_id is None:
                return _error(ErrorCode.FORBIDDEN)
        try:
            command = model.model_validate_json(arguments_json)
        except ValidationError:
            return _error(ErrorCode.VALIDATION_ERROR)

        try:
            if isinstance(command, CaseSearch):
                candidates = await self.cases.search(command, context)
                return ToolResult(
                    ok=True,
                    data={"candidates": [item.model_dump(mode="json") for item in candidates]},
                )
            if isinstance(command, CaseGet):
                case = await self.cases.get(command.case_id, context)
                if case is None:
                    return _error(ErrorCode.INSUFFICIENT_CONTEXT)
                return ToolResult(
                    ok=True,
                    data=case.model_dump(mode="json"),
                    entity_version=case.version,
                    source_refs=case.source_refs,
                )
            if isinstance(command, CaseCreate):
                case = await self.cases.create(command, context)
                return ToolResult(
                    ok=True,
                    data={"case_id": str(case.case_id)},
                    entity_version=case.version,
                    source_refs=case.source_refs,
                    operation_id=command.operation_id,
                )
            if isinstance(command, CaseAttachMessage):
                case = await self.cases.attach_message(command, context)
                return ToolResult(
                    ok=True,
                    data={"case_id": str(case.case_id)},
                    entity_version=case.version,
                    source_refs=case.source_refs,
                    operation_id=command.operation_id,
                )
            if isinstance(command, KnowledgeSearch):
                hits = await self.knowledge.search(command, context)
                return ToolResult(
                    ok=True,
                    data={"hits": [hit.model_dump(mode="json") for hit in hits]},
                    source_refs=tuple(f"{hit.source_id}:{hit.revision}" for hit in hits),
                )
            if isinstance(command, RequestPrepare):
                request = await self.requests.prepare(command, context)
                return ToolResult(
                    ok=True,
                    data={"request_id": str(request.request_id), "status": request.status},
                    entity_version=request.draft_version,
                    operation_id=command.operation_id,
                )
            if isinstance(command, RequestSubmit):
                request = await self.requests.submit(command, context)
                return ToolResult(
                    ok=True,
                    data={"request_id": str(request.request_id), "status": request.status},
                    entity_version=request.draft_version,
                    operation_id=command.operation_id,
                )
            if isinstance(command, RequestGetStatus):
                status_view = await self.requests.get_status(command.request_id, context)
                if status_view is None:
                    return _error(ErrorCode.INSUFFICIENT_CONTEXT)
                return ToolResult(
                    ok=True,
                    data=status_view.model_dump(mode="json"),
                    entity_version=status_view.draft_version,
                )
        except ValueError as exc:
            if str(exc) == "VERSION_CONFLICT":
                return _error(ErrorCode.VERSION_CONFLICT)
            if str(exc) in {"CASE_NOT_FOUND", "REQUEST_NOT_FOUND"}:
                return _error(ErrorCode.INSUFFICIENT_CONTEXT)
            if str(exc) == "MESSAGE_ALREADY_ATTACHED":
                return _error(ErrorCode.CONFLICT)
            raise
        raise AssertionError("Неизвестная модель tool")
