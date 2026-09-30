"""Stable synthetic house data used by the demo seed.

This module intentionally lives in the runtime package: a production image does not
contain the test suite, but a clean demo stand still needs deterministic residents.
The identifiers do not belong to real people.
"""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from dom_domych.domain.audiences.models import RiserRef


def synthetic_id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"dom-domich-demo:{name}")


HOUSE_ONE = synthetic_id("house-one")
HOUSE_TWO = synthetic_id("house-two")
RISER_E2_A = synthetic_id("house-one:cold-water:e2-a")
RISER_E2_B = synthetic_id("house-one:cold-water:e2-b")
RISER_E2_HEAT = synthetic_id("house-one:heating:e2")
RISER_E1 = synthetic_id("house-one:cold-water:e1")


@dataclass(frozen=True, slots=True)
class DemoResidency:
    resident_id: UUID
    apartment_id: UUID
    apartment_number: str
    house_id: UUID
    entrance: int
    floor: int
    risers: frozenset[RiserRef]
    confirmed: bool
    adult: bool
    active: bool
    dm_reachable: bool


def _residency(
    resident_number: int,
    apartment: str,
    *,
    house_id: UUID = HOUSE_ONE,
    entrance: int = 2,
    floor: int = 5,
    risers: frozenset[UUID] = frozenset({RISER_E2_A, RISER_E2_HEAT}),
    confirmed: bool = True,
    adult: bool = True,
    active: bool = True,
    dm_reachable: bool = True,
) -> DemoResidency:
    return DemoResidency(
        resident_id=synthetic_id(f"resident-{resident_number}"),
        apartment_id=synthetic_id(f"{house_id}:apartment-{apartment}"),
        apartment_number=apartment,
        house_id=house_id,
        entrance=entrance,
        floor=floor,
        risers=frozenset(
            RiserRef(riser_id=item, kind="heating" if item == RISER_E2_HEAT else "cold_water")
            for item in risers
        ),
        confirmed=confirmed,
        adult=adult,
        active=active,
        dm_reachable=dm_reachable,
    )


def demo_residencies() -> tuple[DemoResidency, ...]:
    """Return the deterministic two-house registry used by the demo stand."""

    floor_five = tuple(
        _residency(
            number,
            apartment=f"{205 + (number - 1) // 2}",
            risers=frozenset({RISER_E2_A if number <= 6 else RISER_E2_B, RISER_E2_HEAT}),
            dm_reachable=number != 10,
        )
        for number in range(1, 13)
    )
    extras = (
        _residency(13, "205", confirmed=False),
        _residency(14, "206", adult=False),
        _residency(15, "105", entrance=1, risers=frozenset({RISER_E1})),
        _residency(16, "106", entrance=1, risers=frozenset({RISER_E1})),
        _residency(17, "211", floor=6, risers=frozenset({RISER_E2_B, RISER_E2_HEAT})),
        _residency(1, "211", floor=6, risers=frozenset({RISER_E2_B, RISER_E2_HEAT})),
        _residency(
            18,
            "211",
            floor=6,
            risers=frozenset({RISER_E2_B, RISER_E2_HEAT}),
            active=False,
        ),
        _residency(
            19,
            "501",
            house_id=HOUSE_TWO,
            entrance=1,
            risers=frozenset({synthetic_id("house-two:cold-water:e1")}),
        ),
    )
    return floor_five + extras
