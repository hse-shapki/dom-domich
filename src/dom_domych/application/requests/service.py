"""K10: draft, approval, demo submit и registration — разные состояния."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.agent.contracts import RequestPrepare, RequestSubmit, RequestView, TrustedContext
from dom_domych.contracts.base import ExecutionMode, PrincipalType
from dom_domych.domain.executor.models import ApprovedDraft, DemoOperation, ExternalStatus
from dom_domych.domain.knowledge.models import RuleVersion


@dataclass(frozen=True, slots=True)
class RequestCase:
    case_id: UUID
    house_id: UUID
    kind: str
    version: int
    status: str
    topic: str
    title: str
    description: str
    location: str


@dataclass(frozen=True, slots=True)
class RequestDraft:
    request_id: UUID
    draft_id: UUID
    case_id: UUID
    house_id: UUID
    draft_version: int
    content_sha256: str
    responsible_id: UUID
    rule_id: UUID
    source_refs: tuple[str, ...]
    status: str
    approved_version: int | None = None
    approval_actor: UUID | None = None
    executor_operation_id: UUID | None = None
    registration_id: str | None = None
    registered_at: datetime | None = None
    external_status: str | None = None
    external_version: int = 0
    document_id: UUID | None = None
    document_snapshot_hash: str | None = None
    document_file_key: UUID | None = None

    def to_view(self) -> RequestView:
        return RequestView(
            request_id=self.request_id,
            case_id=self.case_id,
            draft_version=self.draft_version,
            status=self.status,
            registration_id=self.registration_id,
            registered_at=self.registered_at,
        )


class RequestCasePort(Protocol):
    async def get_for_request(self, case_id: UUID, house_id: UUID) -> RequestCase | None: ...


class VerifiedRulePort(Protocol):
    async def find_rule(self, topic: str, house_id: UUID, at: datetime) -> RuleVersion | None: ...


class RequestStore(Protocol):
    async def get_prepare_operation(
        self, house_id: UUID, operation_id: UUID, command_hash: str
    ) -> RequestDraft | None: ...
    async def prepare_once(
        self,
        draft: RequestDraft,
        expected_case_version: int,
        operation_id: UUID,
        command_hash: str,
    ) -> RequestDraft: ...
    async def get(self, request_id: UUID, house_id: UUID) -> RequestDraft | None: ...
    async def revise(
        self,
        request_id: UUID,
        house_id: UUID,
        expected_version: int,
        content_sha256: str,
        operation_id: UUID,
    ) -> RequestDraft: ...
    async def approve(
        self, request_id: UUID, house_id: UUID, expected_version: int, actor_id: UUID
    ) -> RequestDraft: ...
    async def reserve_submit(
        self, request_id: UUID, house_id: UUID, expected_version: int, operation_id: UUID
    ) -> RequestDraft: ...
    async def mark_submitted(
        self, request_id: UUID, house_id: UUID, operation_id: UUID, executor_operation_id: UUID
    ) -> RequestDraft: ...
    async def register(
        self, request_id: UUID, house_id: UUID, operation: DemoOperation
    ) -> RequestDraft: ...


class DemoSubmitPort(Protocol):
    async def submit(
        self, draft: ApprovedDraft, operation_key: str, house_id: UUID
    ) -> DemoOperation: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class RequestService:
    """Источник правила и результат executor проверяются backend, не моделью."""

    def __init__(
        self,
        cases: RequestCasePort,
        rules: VerifiedRulePort,
        store: RequestStore,
        executor: DemoSubmitPort,
        clock: Clock,
    ) -> None:
        self.cases = cases
        self.rules = rules
        self.store = store
        self.executor = executor
        self.clock = clock

    async def prepare(self, command: RequestPrepare, context: TrustedContext) -> RequestView:
        self._require(context, "request.write")
        command_hash = sha256(
            json.dumps(
                {"command": command.model_dump(mode="json"), "actor_id": str(context.actor_id)},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        prior = await self.store.get_prepare_operation(
            context.house_id, command.operation_id, command_hash
        )
        if prior is not None:
            return prior.to_view()
        case = await self.cases.get_for_request(command.case_id, context.house_id)
        if case is None or case.version != command.expected_case_version:
            raise ValueError("VERSION_CONFLICT")
        allowed = case.status == "request_ready" or (
            case.kind == "emergency" and case.status in {"detected", "preparing_request"}
        )
        if (
            not allowed
            or not case.title.strip()
            or not case.description.strip()
            or not case.location.strip()
        ):
            raise ValueError("INSUFFICIENT_CONTEXT")
        now = self.clock.now()
        rule = await self.rules.find_rule(case.topic, context.house_id, now)
        if (
            rule is None
            or not rule.is_applicable(context.house_id, case.topic, now)
            or rule.responsible_id != command.responsible_id
        ):
            raise ValueError("UNVERIFIED_RESPONSIBLE")
        rule_ref = f"{rule.source_id}:{rule.source_revision}"
        if rule_ref not in command.source_refs:
            raise ValueError("SOURCE_REF_MISSING")
        if set(command.source_refs) != {rule_ref}:
            raise ValueError("SOURCE_REF_UNVERIFIED")
        verified_refs = tuple(sorted(set(command.source_refs)))
        snapshot = {
            "case_id": str(case.case_id),
            "case_version": case.version,
            "title": case.title,
            "description": case.description,
            "location": case.location,
            "responsible_id": str(rule.responsible_id),
            "rule_id": str(rule.rule_id),
            "source_refs": verified_refs,
        }
        digest = sha256(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        draft = RequestDraft(
            request_id=uuid4(),
            draft_id=uuid4(),
            case_id=case.case_id,
            house_id=context.house_id,
            draft_version=1,
            content_sha256=digest,
            responsible_id=rule.responsible_id,
            rule_id=rule.rule_id,
            source_refs=verified_refs,
            status="prepared",
        )
        return (
            await self.store.prepare_once(draft, case.version, command.operation_id, command_hash)
        ).to_view()

    async def revise(
        self,
        request_id: UUID,
        expected_version: int,
        content: str,
        operation_id: UUID,
        context: TrustedContext,
    ) -> RequestView:
        self._require(context, "request.write")
        if len(content.strip()) < 10:
            raise ValueError("INSUFFICIENT_CONTEXT")
        digest = sha256(content.strip().encode()).hexdigest()
        return (
            await self.store.revise(
                request_id, context.house_id, expected_version, digest, operation_id
            )
        ).to_view()

    async def approve(
        self, request_id: UUID, expected_version: int, context: TrustedContext
    ) -> RequestView:
        self._require(context, "request.approve")
        assert context.actor_id is not None
        return (
            await self.store.approve(
                request_id, context.house_id, expected_version, context.actor_id
            )
        ).to_view()

    async def submit(self, command: RequestSubmit, context: TrustedContext) -> RequestView:
        self._require(context, "request.submit")
        if context.mode != ExecutionMode.DEMO:
            raise ValueError("LIVE_SUBMISSION_NOT_CONFIGURED")
        reserved = await self.store.reserve_submit(
            command.request_id,
            context.house_id,
            command.expected_draft_version,
            command.operation_id,
        )
        if reserved.status in {"submitted", "registered"}:
            return reserved.to_view()
        approved_draft = ApprovedDraft(
            house_id=context.house_id,
            request_id=reserved.request_id,
            draft_id=reserved.draft_id,
            draft_revision=reserved.draft_version,
            content_sha256=reserved.content_sha256,
        )
        operation = await self.executor.submit(
            approved_draft,
            str(command.operation_id),
            context.house_id,
        )
        if operation.draft != approved_draft or operation.status != ExternalStatus.SUBMITTED:
            raise ValueError("EXECUTOR_RESULT_MISMATCH")
        return (
            await self.store.mark_submitted(
                reserved.request_id,
                context.house_id,
                command.operation_id,
                operation.operation_id,
            )
        ).to_view()

    async def record_registration(
        self, operation: DemoOperation, context: TrustedContext
    ) -> RequestView:
        if (
            context.principal_type != PrincipalType.WORKER
            or "request.record_registration" not in context.capabilities
            or operation.draft.house_id != context.house_id
            or operation.status
            not in {
                ExternalStatus.REGISTERED,
                ExternalStatus.IN_PROGRESS,
                ExternalStatus.DONE,
            }
            or operation.registration_number is None
            or operation.registered_at is None
        ):
            raise PermissionError("FORBIDDEN")
        return (
            await self.store.register(operation.draft.request_id, context.house_id, operation)
        ).to_view()

    async def get_status(self, request_id: UUID, context: TrustedContext) -> RequestView | None:
        if "request.read" not in context.capabilities:
            raise PermissionError("FORBIDDEN")
        draft = await self.store.get(request_id, context.house_id)
        return draft.to_view() if draft is not None else None

    @staticmethod
    def _require(context: TrustedContext, capability: str) -> None:
        if capability not in context.capabilities or context.actor_id is None:
            raise PermissionError("FORBIDDEN")
