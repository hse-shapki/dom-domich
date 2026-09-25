"""Синтетические данные пула Z; идентификаторы не относятся к настоящим людям."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
class FixtureResidency:
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

    @property
    def riser_ids(self) -> frozenset[UUID]:
        return frozenset(item.riser_id for item in self.risers)


@dataclass(frozen=True, slots=True)
class FixtureMessage:
    message_id: UUID
    house_id: UUID
    author_id: UUID
    text: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class ZamiraFixture:
    residencies: tuple[FixtureResidency, ...]
    same_problem_messages: tuple[FixtureMessage, ...]
    repeated_messages: tuple[FixtureMessage, ...]
    different_problem_message: FixtureMessage
    opened_at: datetime
    closes_at: datetime
    late_answer_at: datetime
    changed_initiative_text: str
    negative_resolution_residents: frozenset[UUID]


class FakeResidentDirectory:
    """Черновой fake HouseContextPort: возвращает записи проживания одного дома."""

    def __init__(self, fixture: ZamiraFixture) -> None:
        self.fixture = fixture

    async def list_house_residencies(self, house_id: UUID) -> tuple[FixtureResidency, ...]:
        return tuple(item for item in self.fixture.residencies if item.house_id == house_id)


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
) -> FixtureResidency:
    return FixtureResidency(
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


def zamira_fixture() -> ZamiraFixture:
    """Двенадцать взрослых на одном этаже плюс исключения для проверки аудитории."""

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
        _residency(18, "211", floor=6, active=False),
        _residency(
            19,
            "501",
            house_id=HOUSE_TWO,
            entrance=1,
            risers=frozenset({synthetic_id("house-two:cold-water:e1")}),
        ),
    )
    opened_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    messages = tuple(
        FixtureMessage(
            message_id=synthetic_id(f"same-problem-{number}"),
            house_id=HOUSE_ONE,
            author_id=synthetic_id(f"resident-{number}"),
            text="Нет воды на пятом этаже второго подъезда",
            received_at=opened_at + timedelta(minutes=number),
        )
        for number in range(1, 13)
    )
    return ZamiraFixture(
        residencies=floor_five + extras,
        same_problem_messages=messages,
        repeated_messages=tuple(
            FixtureMessage(
                message_id=synthetic_id(f"same-problem-repeated-{number}"),
                house_id=HOUSE_ONE,
                author_id=synthetic_id("resident-1"),
                text="Всё ещё нет воды",
                received_at=opened_at + timedelta(minutes=20 + number),
            )
            for number in range(12)
        ),
        different_problem_message=FixtureMessage(
            message_id=synthetic_id("different-problem"),
            house_id=HOUSE_ONE,
            author_id=synthetic_id("resident-15"),
            text="Нет воды в первом подъезде",
            received_at=opened_at + timedelta(minutes=21),
        ),
        opened_at=opened_at,
        closes_at=opened_at + timedelta(hours=5),
        late_answer_at=opened_at + timedelta(hours=5, seconds=1),
        changed_initiative_text="Установить велопарковку у второго подъезда и навес",
        negative_resolution_residents=frozenset(
            {synthetic_id("resident-1"), synthetic_id("resident-2")}
        ),
    )
