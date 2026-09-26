"""K11: срочная подготовка обращения без ожидания коллективного порога."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from dom_domych.agent.contracts import RequestPrepare, RequestView, TrustedContext
from dom_domych.application.requests.service import RequestCase, RequestCasePort, VerifiedRulePort


class RequestPreparer(Protocol):
    async def prepare(self, command: RequestPrepare, context: TrustedContext) -> RequestView: ...


class EmergencyEvidencePort(Protocol):
    async def queue_private(
        self, case_id: UUID, context: TrustedContext, operation_key: str
    ) -> UUID: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class EmergencyOutcome:
    case_id: UUID
    status: Literal["clarify_location", "needs_verified_responsible", "prepared"]
    urgency_source_ref: str
    evidence_delivery_id: UUID
    request_id: UUID | None = None
    rule_source_ref: str | None = None
    deadline: timedelta | None = None
    deadline_origin: str | None = None


class EmergencyService:
    """Evidence ставится отдельно, поэтому отсутствие фото не блокирует draft."""

    def __init__(
        self,
        cases: RequestCasePort,
        rules: VerifiedRulePort,
        requests: RequestPreparer,
        evidence: EmergencyEvidencePort,
        clock: Clock,
    ) -> None:
        self.cases = cases
        self.rules = rules
        self.requests = requests
        self.evidence = evidence
        self.clock = clock

    async def handle(
        self, case_id: UUID, expected_case_version: int, context: TrustedContext
    ) -> EmergencyOutcome:
        if "emergency.handle" not in context.capabilities or context.actor_id is None:
            raise PermissionError("FORBIDDEN")
        case = await self.cases.get_for_request(case_id, context.house_id)
        if case is None or case.kind != "emergency":
            raise ValueError("EMERGENCY_CASE_NOT_FOUND")
        urgency_ref = f"event:{context.event_id}"
        evidence_key = f"emergency:evidence:{case_id}:{context.event_id}"
        if not self._has_precise_location(case):
            evidence_id = await self.evidence.queue_private(case_id, context, evidence_key)
            return EmergencyOutcome(case_id, "clarify_location", urgency_ref, evidence_id)
        now = self.clock.now()
        rule = await self.rules.find_rule(case.topic, context.house_id, now)
        if rule is None or not rule.is_applicable(context.house_id, case.topic, now):
            evidence_id = await self.evidence.queue_private(case_id, context, evidence_key)
            return EmergencyOutcome(case_id, "needs_verified_responsible", urgency_ref, evidence_id)
        rule_ref = f"{rule.source_id}:{rule.source_revision}"
        operation_id = uuid5(NAMESPACE_URL, f"emergency:prepare:{case_id}:{expected_case_version}")
        prepared = await self.requests.prepare(
            RequestPrepare(
                case_id=case_id,
                expected_case_version=expected_case_version,
                responsible_id=rule.responsible_id,
                source_refs=(rule_ref,),
                operation_id=operation_id,
            ),
            context,
        )
        evidence_id = await self.evidence.queue_private(case_id, context, evidence_key)
        return EmergencyOutcome(
            case_id,
            "prepared",
            urgency_ref,
            evidence_id,
            request_id=prepared.request_id,
            rule_source_ref=rule_ref,
            deadline=rule.deadline,
            deadline_origin=rule.deadline_origin,
        )

    @staticmethod
    def _has_precise_location(case: RequestCase) -> bool:
        return bool(case.location.strip() and case.topic.strip())
