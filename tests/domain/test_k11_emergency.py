"""K11: срочный маршрут не ждёт poll и не выдумывает нормативный срок."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from dom_domych.agent.contracts import RequestPrepare, RequestView, TrustedContext
from dom_domych.application.requests.emergency import EmergencyService
from dom_domych.application.requests.service import RequestCase
from dom_domych.contracts.base import ExecutionMode, PrincipalType
from dom_domych.domain.knowledge.models import RuleVersion

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class Cases:
    def __init__(self, case: RequestCase) -> None:
        self.case = case

    async def get_for_request(self, case_id: UUID, house_id: UUID) -> RequestCase | None:
        return self.case if (case_id, house_id) == (self.case.case_id, self.case.house_id) else None


class Rules:
    def __init__(self, rule: RuleVersion | None) -> None:
        self.rule = rule

    async def find_rule(self, topic: str, house_id: UUID, at: datetime) -> RuleVersion | None:
        return self.rule


class Requests:
    def __init__(self) -> None:
        self.calls: list[RequestPrepare] = []
        self.request_id = uuid4()

    async def prepare(self, command: RequestPrepare, context: TrustedContext) -> RequestView:
        self.calls.append(command)
        return RequestView(
            request_id=self.request_id,
            case_id=command.case_id,
            draft_version=1,
            status="prepared",
        )


class Evidence:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.id = uuid4()

    async def queue_private(
        self, case_id: UUID, context: TrustedContext, operation_key: str
    ) -> UUID:
        self.keys.append(operation_key)
        return self.id


def _context(house_id: UUID) -> TrustedContext:
    return TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=house_id,
        actor_id=uuid4(),
        principal_type=PrincipalType.RESIDENT,
        capabilities=frozenset({"emergency.handle", "request.write"}),
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )


@pytest.mark.asyncio
async def test_emergency_prepares_immediately_and_evidence_is_separate() -> None:
    house_id, case_id = uuid4(), uuid4()
    case = RequestCase(
        case_id, house_id, "emergency", 2, "detected", "leak", "Течёт", "Течёт вода", "подъезд 1"
    )
    rule = RuleVersion(uuid4(), uuid4(), 1, house_id, "leak", uuid4(), None, None)
    requests, evidence = Requests(), Evidence()
    service = EmergencyService(Cases(case), Rules(rule), requests, evidence, FixedClock())
    context = _context(house_id)
    result = await service.handle(case_id, 2, context)
    assert result.status == "prepared" and result.request_id == requests.request_id
    assert result.deadline is None and result.deadline_origin is None
    assert len(requests.calls) == 1
    assert requests.calls[0].source_refs == (f"{rule.source_id}:1",)
    assert evidence.keys == [f"emergency:evidence:{case_id}:{context.event_id}"]


@pytest.mark.asyncio
async def test_missing_location_or_rule_requests_clarification_without_poll() -> None:
    house_id, case_id = uuid4(), uuid4()
    case = RequestCase(
        case_id, house_id, "emergency", 1, "detected", "leak", "Течёт", "Течёт вода", ""
    )
    requests, evidence = Requests(), Evidence()
    service = EmergencyService(Cases(case), Rules(None), requests, evidence, FixedClock())
    context = _context(house_id)
    assert (await service.handle(case_id, 1, context)).status == "clarify_location"
    assert requests.calls == []
    located = RequestCase(
        case_id, house_id, "emergency", 1, "detected", "leak", "Течёт", "Течёт вода", "подъезд 1"
    )
    service = EmergencyService(Cases(located), Rules(None), requests, evidence, FixedClock())
    assert (await service.handle(case_id, 1, context)).status == "needs_verified_responsible"
    assert requests.calls == []
