"""Проверки контрактов, по которым K/Z могут продолжать независимо от MAX и PostgreSQL."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.contracts.errors import ContractError, ErrorCode
from dom_domych.contracts.events import (
    CallbackPayload,
    EventEnvelope,
    EventName,
    EventSource,
    MessagePayload,
)
from dom_domych.contracts.tools import ToolResult
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.ports.core import HouseContextPort
from tests.fakes.house import FakeHouseContext
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO, zamira_fixture


def test_event_rejects_float_external_ids_and_wrong_payload() -> None:
    base = {
        "event_id": uuid4(),
        "source": EventSource.MAX,
        "source_key": "message:1",
        "name": EventName.MESSAGE_RECEIVED,
        "occurred_at": datetime.now(UTC),
        "received_at": datetime.now(UTC),
        "correlation_id": uuid4(),
    }
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(
            {**base, "message": {"chat_id": 1.5, "message_id": "1", "sender_user_id": "2"}}
        )
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(
            {
                **base,
                "callback": CallbackPayload(callback_id="1", sender_user_id="2", action_token="x"),
            }
        )


def test_trusted_context_requires_utc_and_no_unknown_model_fields() -> None:
    values = {
        "run_id": uuid4(),
        "event_id": uuid4(),
        "house_id": HOUSE_ONE,
        "actor_id": uuid4(),
        "principal_type": PrincipalType.RESIDENT,
        "correlation_id": uuid4(),
        "mode": ExecutionMode.DEMO,
    }
    with pytest.raises(ValidationError):
        TrustedContext.model_validate({**values, "deadline": datetime(2026, 9, 25, 12)})
    with pytest.raises(ValidationError):
        TrustedContext.model_validate({**values, "house_id_from_model": HOUSE_TWO})
    context = TrustedContext.model_validate(values)
    assert context.house_id == HOUSE_ONE


def test_tool_result_cannot_report_unchecked_success() -> None:
    with pytest.raises(ValidationError):
        ToolResult(ok=False)
    with pytest.raises(ValidationError):
        ToolResult(ok=True, error=ContractError(code=ErrorCode.FORBIDDEN))
    assert ToolResult(ok=False, error=ContractError(code=ErrorCode.FORBIDDEN)).ok is False


@pytest.mark.asyncio
async def test_shared_house_port_matches_zamira_audience_fixture() -> None:
    fake: HouseContextPort = FakeHouseContext(zamira_fixture())
    rows = await fake.list_house_residencies(HOUSE_ONE)
    scope = AudienceScope(kind=ScopeKind.FLOOR, entrance=2, floor=5)
    eligible = {
        row.resident_id
        for row in rows
        if row.confirmed and row.adult and row.active and scope.matches(row)
    }
    assert len(eligible) == 12
    assert len(await fake.list_house_residencies(HOUSE_TWO)) == 1


def test_event_round_trip_preserves_exact_external_ids() -> None:
    event = EventEnvelope(
        event_id=uuid4(),
        source=EventSource.MAX,
        source_key="message:9007199254740993",
        name=EventName.MESSAGE_RECEIVED,
        occurred_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        correlation_id=uuid4(),
        message=MessagePayload(
            chat_id="9007199254740993", message_id="123", sender_user_id="456", text="Нет воды"
        ),
    )
    restored = EventEnvelope.model_validate_json(event.model_dump_json())
    assert restored.message is not None
    assert restored.message.chat_id == "9007199254740993"
