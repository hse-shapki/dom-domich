"""House-scoped adapter реестра для выбора аудитории и доверенного контекста."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.domain.ports.core import Clock, RiserRef
from dom_domych.infrastructure.postgres.models import (
    ApartmentRiserRow,
    ApartmentRow,
    HouseRow,
    ResidencyRow,
    ResidentRow,
    RiserRow,
)


@dataclass(frozen=True, slots=True)
class ResidencyRecord:
    resident_id: UUID
    house_id: UUID
    apartment_id: UUID
    entrance: int
    floor: int
    risers: frozenset[RiserRef]
    confirmed: bool
    adult: bool
    active: bool
    dm_reachable: bool


class PostgresHouseContext:
    """Один instance использует только переданную session текущей Unit of Work."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    async def list_house_residencies(self, house_id: UUID) -> tuple[ResidencyRecord, ...]:
        """Возвращает raw проживания, включая неподтверждённых; Z фильтрует eligibility."""

        statement = (
            select(ResidencyRow, ApartmentRow, ResidentRow)
            .join(
                ApartmentRow,
                (ApartmentRow.id == ResidencyRow.apartment_id)
                & (ApartmentRow.house_id == ResidencyRow.house_id),
            )
            .join(ResidentRow, ResidentRow.id == ResidencyRow.resident_id)
            .where(ResidencyRow.house_id == house_id)
            .order_by(ResidencyRow.id)
        )
        rows = (await self.session.execute(statement)).all()
        if not rows:
            return ()
        riser_rows = (
            await self.session.execute(
                select(ApartmentRiserRow.apartment_id, RiserRow.id, RiserRow.kind)
                .join(
                    RiserRow,
                    (RiserRow.id == ApartmentRiserRow.riser_id)
                    & (RiserRow.house_id == ApartmentRiserRow.house_id),
                )
                .where(ApartmentRiserRow.house_id == house_id)
            )
        ).all()
        risers: dict[UUID, set[RiserRef]] = {}
        for apartment_id, riser_id, kind in riser_rows:
            risers.setdefault(apartment_id, set()).add(RiserRef(riser_id, kind))
        now = self.clock.now()
        return tuple(
            self._to_record(
                residency, apartment, resident, frozenset(risers.get(apartment.id, set())), now
            )
            for residency, apartment, resident in rows
        )

    @staticmethod
    def _to_record(
        residency: ResidencyRow,
        apartment: ApartmentRow,
        resident: ResidentRow,
        risers: frozenset[RiserRef],
        now: datetime,
    ) -> ResidencyRecord:
        active = residency.valid_from <= now and (
            residency.valid_until is None or now < residency.valid_until
        )
        return ResidencyRecord(
            resident_id=resident.id,
            house_id=residency.house_id,
            apartment_id=apartment.id,
            entrance=apartment.entrance,
            floor=apartment.floor,
            risers=risers,
            confirmed=residency.confirmed,
            adult=residency.adult,
            active=active,
            dm_reachable=resident.dm_reachable,
        )

    async def resident_for_max_user(self, max_user_id: str) -> UUID | None:
        return await self.session.scalar(
            select(ResidentRow.id).where(ResidentRow.max_user_id == max_user_id)
        )

    async def house_for_chat(self, max_chat_id: str) -> UUID | None:
        return await self.session.scalar(
            select(HouseRow.id).where(HouseRow.max_chat_id == max_chat_id)
        )
