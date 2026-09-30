"""Заполняет синтетический дом Z02 в явно разрешённой demo/test PostgreSQL."""

import argparse
import asyncio
import os
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.demo.house import HOUSE_ONE, HOUSE_TWO, demo_residencies
from dom_domych.infrastructure.postgres.knowledge_models import (
    KnowledgeSourceRow,
    RuleVersionRow,
)
from dom_domych.infrastructure.postgres.models import (
    ApartmentRiserRow,
    ApartmentRow,
    HouseRow,
    ResidencyRow,
    ResidentRow,
    RiserRow,
)
from dom_domych.infrastructure.postgres.session import database_lifespan


async def _insert_once(
    session: AsyncSession, table: type[object], values: dict[str, object]
) -> None:
    statement = insert(table).values(**values).on_conflict_do_nothing()
    await session.execute(statement)


async def seed_demo_house(session: AsyncSession) -> None:
    """Идемпотентный seed; существующие записи и права не перезаписываются."""

    residencies = demo_residencies()
    for house_id, address in (
        (HOUSE_ONE, "Демо: Москва, Тестовая улица, дом 1"),
        (HOUSE_TWO, "Демо: Москва, Тестовая улица, дом 2"),
    ):
        await _insert_once(
            session,
            HouseRow,
            {"id": house_id, "address": address, "timezone": "Europe/Moscow", "demo": True},
        )

    residents = {row.resident_id: row for row in residencies}
    apartments = {row.apartment_id: row for row in residencies}
    for row in residencies:
        if row.risers != apartments[row.apartment_id].risers:
            raise ValueError("one apartment cannot have conflicting riser memberships")
    risers = {(row.house_id, riser.riser_id): riser for row in residencies for riser in row.risers}
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
    for row in residencies:
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


async def seed_demo_service_routes(session: AsyncSession) -> None:
    """Только для тестового стенда: проверенные синтетические маршруты, без правовых сроков."""

    routes = (
        ("lighting", "Аварийно-диспетчерская служба управляющей организации"),
        ("water_supply", "Аварийно-диспетчерская служба управляющей организации"),
        ("heating", "Аварийно-диспетчерская служба управляющей организации"),
        ("elevator", "Лифтовая диспетчерская служба"),
    )
    for house_id in (HOUSE_ONE, HOUSE_TWO):
        for topic, responsible_name in routes:
            source_id = uuid5(NAMESPACE_URL, f"dom-domich-demo:service-source:{house_id}:{topic}")
            await _insert_once(
                session,
                KnowledgeSourceRow,
                {
                    "source_id": source_id,
                    "revision": 1,
                    "house_id": house_id,
                    "title": f"Тестовый маршрут: {topic}",
                    "uri": f"demo://service-routes/{topic}",
                    "text": (
                        f"Для темы {topic} в демонстрационном доме выбрана служба: "
                        f"{responsible_name}. Это не официальный справочник исполнителей."
                    ),
                    "reviewed": True,
                    "valid_from": None,
                    "valid_until": None,
                },
            )
            await _insert_once(
                session,
                RuleVersionRow,
                {
                    "id": uuid5(NAMESPACE_URL, f"dom-domich-demo:service-rule:{house_id}:{topic}"),
                    "source_id": source_id,
                    "source_revision": 1,
                    "house_id": house_id,
                    "topic": topic,
                    "responsible_id": uuid5(
                        NAMESPACE_URL, f"dom-domich-demo:service:{house_id}:{responsible_name}"
                    ),
                    "responsible_name": responsible_name,
                    "duration_seconds": None,
                    "deadline_origin": None,
                    "valid_from": None,
                    "valid_until": None,
                },
            )


def _demo_seed_allowed(database_url: str, *, explicit_demo: bool) -> bool:
    database = make_url(database_url).database or ""
    return database.startswith("dom_domych_test") or (
        explicit_demo and database == "dom_domych_demo"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-demo-database",
        action="store_true",
        help="allow seeding only a database whose name contains dom_domych_demo",
    )
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url or not _demo_seed_allowed(
        database_url, explicit_demo=args.allow_demo_database
    ):
        raise RuntimeError(
            "seed requires a dom_domych_test database or --allow-demo-database "
            "with a dom_domych_demo database"
        )
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await seed_demo_service_routes(session)


if __name__ == "__main__":
    asyncio.run(main())
