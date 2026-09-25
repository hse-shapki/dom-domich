"""Заполняет только синтетический дом Z02 в явно указанной тестовой PostgreSQL."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.infrastructure.postgres.models import (
    ApartmentRiserRow,
    ApartmentRow,
    HouseRow,
    ResidencyRow,
    ResidentRow,
    RiserRow,
)
from dom_domych.infrastructure.postgres.session import database_lifespan
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO, zamira_fixture


async def _insert_once(
    session: AsyncSession, table: type[object], values: dict[str, object]
) -> None:
    statement = insert(table).values(**values).on_conflict_do_nothing()
    await session.execute(statement)


async def seed_demo_house(session: AsyncSession) -> None:
    """Идемпотентный seed; существующие записи и права не перезаписываются."""

    fixture = zamira_fixture()
    for house_id, address in (
        (HOUSE_ONE, "Демо: Москва, Тестовая улица, дом 1"),
        (HOUSE_TWO, "Демо: Москва, Тестовая улица, дом 2"),
    ):
        await _insert_once(
            session,
            HouseRow,
            {"id": house_id, "address": address, "timezone": "Europe/Moscow", "demo": True},
        )

    residents = {row.resident_id: row for row in fixture.residencies}
    apartments = {row.apartment_id: row for row in fixture.residencies}
    risers = {
        (row.house_id, riser.riser_id): riser for row in fixture.residencies for riser in row.risers
    }
    for resident_id, row in residents.items():
        await _insert_once(
            session,
            ResidentRow,
            {
                "id": resident_id,
                "max_user_id": None,
                "display_name": f"Тестовый житель {str(resident_id)[:8]}",
                "dm_reachable": row.dm_reachable,
            },
        )
    for apartment_id, row in apartments.items():
        await _insert_once(
            session,
            ApartmentRow,
            {
                "id": apartment_id,
                "house_id": row.house_id,
                "number": row.apartment_number,
                "entrance": row.entrance,
                "floor": row.floor,
            },
        )
    for (house_id, riser_id), riser in risers.items():
        await _insert_once(
            session,
            RiserRow,
            {"id": riser_id, "house_id": house_id, "kind": riser.kind, "label": str(riser_id)},
        )
    for row in fixture.residencies:
        for riser in row.risers:
            await _insert_once(
                session,
                ApartmentRiserRow,
                {
                    "house_id": row.house_id,
                    "apartment_id": row.apartment_id,
                    "riser_id": riser.riser_id,
                },
            )
        await _insert_once(
            session,
            ResidencyRow,
            {
                "id": uuid5(
                    NAMESPACE_URL,
                    f"dom-domich-demo:residency:{row.house_id}:{row.apartment_id}:{row.resident_id}",
                ),
                "house_id": row.house_id,
                "apartment_id": row.apartment_id,
                "resident_id": row.resident_id,
                "confirmed": row.confirmed,
                "adult": row.adult,
                "valid_from": datetime(2026, 1, 1, tzinfo=UTC),
                "valid_until": datetime(2026, 9, 1, tzinfo=UTC) if not row.active else None,
                "source": "demo",
            },
        )


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url or "dom_domych_test" not in database_url:
        raise RuntimeError("seed requires an explicit test DATABASE_URL containing dom_domych_test")
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)


if __name__ == "__main__":
    asyncio.run(main())
