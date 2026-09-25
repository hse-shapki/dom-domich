"""Подтверждение квартиры через одноразовое приглашение demo operator."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from dom_domych.domain.ports.core import Clock


class EnrollmentDenied(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TrustedDemoOperator:
    house_id: UUID
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    resident_id: UUID
    house_id: UUID
    apartment_id: UUID
    entrance: int
    floor: int


@dataclass(frozen=True, slots=True)
class HouseSelection:
    selected_house_id: UUID | None
    available_house_ids: tuple[UUID, ...]


class EnrollmentPort(Protocol):
    async def issue_invitation(
        self, residency_id: UUID, house_id: UUID, expires_at: datetime, now: datetime
    ) -> str: ...

    async def redeem_invitation(
        self, token: str, max_user_id: str, now: datetime
    ) -> EnrollmentResult: ...

    async def house_selection(self, max_user_id: str, now: datetime) -> HouseSelection: ...

    async def select_house(self, max_user_id: str, house_id: UUID, now: datetime) -> None: ...

    async def set_dm_reachable(self, max_user_id: str, reachable: bool) -> bool: ...

    async def bind_house_chat(self, house_id: UUID, max_chat_id: str) -> None: ...


class DemoEnrollmentService:
    """Operator подтверждает квартиру/возраст до выдачи кода; житель вводит его в MAX."""

    def __init__(self, port: EnrollmentPort, clock: Clock) -> None:
        self.port = port
        self.clock = clock

    async def issue_invitation(
        self,
        residency_id: UUID,
        operator: TrustedDemoOperator,
        *,
        adult_verified: bool,
        ttl: timedelta = timedelta(hours=24),
    ) -> str:
        if "demo.residency_confirm" not in operator.capabilities or not adult_verified:
            raise EnrollmentDenied("demo operator verification required")
        if ttl <= timedelta(0) or ttl > timedelta(days=7):
            raise ValueError("invitation lifetime must be within seven days")
        now = self.clock.now()
        return await self.port.issue_invitation(residency_id, operator.house_id, now + ttl, now)

    async def redeem(self, token: str, max_user_id: str) -> EnrollmentResult:
        if not token or not max_user_id.isdecimal():
            raise EnrollmentDenied("valid invitation and MAX user required")
        return await self.port.redeem_invitation(token, max_user_id, self.clock.now())

    async def current_house(self, max_user_id: str) -> HouseSelection:
        return await self.port.house_selection(max_user_id, self.clock.now())

    async def choose_house(self, max_user_id: str, house_id: UUID) -> HouseSelection:
        await self.port.select_house(max_user_id, house_id, self.clock.now())
        return await self.current_house(max_user_id)

    async def bot_started(self, max_user_id: str) -> bool:
        return await self.port.set_dm_reachable(max_user_id, True)

    async def bot_stopped(self, max_user_id: str) -> bool:
        return await self.port.set_dm_reachable(max_user_id, False)

    async def connect_house_chat(self, max_chat_id: str, operator: TrustedDemoOperator) -> None:
        if "demo.house_chat_bind" not in operator.capabilities or not max_chat_id.isdecimal():
            raise EnrollmentDenied("demo operator and MAX chat required")
        await self.port.bind_house_chat(operator.house_id, max_chat_id)
