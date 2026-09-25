"""Адаптер к общей синтетической fixture для contract tests A01."""

from collections.abc import Sequence
from uuid import UUID

from dom_domych.domain.ports.core import ResidencyView
from tests.fixtures.zamira_house import ZamiraFixture


class FakeHouseContext:
    def __init__(self, fixture: ZamiraFixture) -> None:
        self.fixture = fixture
        self.user_to_resident: dict[str, UUID] = {}
        self.chat_to_house: dict[str, UUID] = {}

    async def list_house_residencies(self, house_id: UUID) -> Sequence[ResidencyView]:
        return tuple(row for row in self.fixture.residencies if row.house_id == house_id)

    async def resident_for_max_user(self, max_user_id: str) -> UUID | None:
        return self.user_to_resident.get(max_user_id)

    async def house_for_chat(self, max_chat_id: str) -> UUID | None:
        return self.chat_to_house.get(max_chat_id)
