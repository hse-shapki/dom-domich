from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest

from dom_domych.application.audiences.service import AudienceService
from dom_domych.domain.audiences.models import (
    AudienceScope,
    AudienceSnapshot,
    ScopeKind,
)
from tests.fixtures.zamira_house import (
    HOUSE_ONE,
    HOUSE_TWO,
    RISER_E2_A,
    RISER_E2_HEAT,
    FakeResidentDirectory,
    FixtureResidency,
    synthetic_id,
    zamira_fixture,
)


@dataclass(frozen=True, slots=True)
class FakeContext:
    house_id: UUID


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


class FakeAudienceRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, AudienceSnapshot] = {}
        self.by_operation: dict[str, UUID] = {}

    async def get(self, audience_id: UUID) -> AudienceSnapshot | None:
        return self.by_id.get(audience_id)

    async def save_once(self, snapshot: AudienceSnapshot, operation_key: str) -> AudienceSnapshot:
        previous_id = self.by_operation.get(operation_key)
        if previous_id is not None:
            previous = self.by_id[previous_id]
            if (
                previous.house_id != snapshot.house_id
                or previous.scope != snapshot.scope
                or previous.supersedes_id != snapshot.supersedes_id
            ):
                raise ValueError("operation key conflicts with a different audience")
            return previous
        if snapshot.supersedes_id is not None and any(
            item.supersedes_id == snapshot.supersedes_id for item in self.by_id.values()
        ):
            raise ValueError("audience revision already superseded")
        self.by_id[snapshot.audience_id] = snapshot
        self.by_operation[operation_key] = snapshot.audience_id
        return snapshot


def service() -> tuple[AudienceService, FakeAudienceRepository]:
    repository = FakeAudienceRepository()
    return AudienceService(
        FakeResidentDirectory(zamira_fixture()), repository, FakeClock()
    ), repository


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "expected_eligible", "expected_reachable"),
    [
        (AudienceScope(kind=ScopeKind.HOUSE), 15, 14),
        (AudienceScope(kind=ScopeKind.ENTRANCE, entrance=1), 2, 2),
        (AudienceScope(kind=ScopeKind.ENTRANCE, entrance=2), 13, 12),
        (AudienceScope(kind=ScopeKind.FLOOR, entrance=2, floor=5), 12, 11),
        (
            AudienceScope(kind=ScopeKind.RISER, riser_id=RISER_E2_A, riser_kind="cold_water"),
            6,
            6,
        ),
        (
            AudienceScope(kind=ScopeKind.RISER, riser_id=RISER_E2_HEAT, riser_kind="heating"),
            13,
            12,
        ),
    ],
)
async def test_resolve_selects_unique_confirmed_adults(
    scope: AudienceScope, expected_eligible: int, expected_reachable: int
) -> None:
    audience_service, _ = service()

    audience = await audience_service.resolve(
        scope, FakeContext(HOUSE_ONE), operation_key=f"scope:{scope}"
    )

    assert audience.eligible_count == expected_eligible
    assert audience.reachable_count == expected_reachable
    assert len({item.resident_id for item in audience.members}) == expected_eligible
    assert audience.house_id == HOUSE_ONE


@pytest.mark.asyncio
async def test_resolve_never_uses_other_house_or_unverified_residents() -> None:
    audience_service, _ = service()

    audience = await audience_service.resolve(
        AudienceScope(kind=ScopeKind.HOUSE),
        FakeContext(HOUSE_TWO),
        operation_key="house-two",
    )

    assert audience.eligible_count == 1
    assert audience.members[0].resident_id == synthetic_id("resident-19")


@pytest.mark.asyncio
async def test_resolve_filters_leaked_other_house_record_again() -> None:
    fixture = zamira_fixture()

    class LeakyDirectory(FakeResidentDirectory):
        async def list_house_residencies(self, house_id: UUID) -> tuple[FixtureResidency, ...]:
            return fixture.residencies

    audience_service = AudienceService(
        LeakyDirectory(fixture), FakeAudienceRepository(), FakeClock()
    )

    audience = await audience_service.resolve(
        AudienceScope(kind=ScopeKind.HOUSE),
        FakeContext(HOUSE_TWO),
        operation_key="leaky-directory",
    )

    assert audience.eligible_count == 1
    assert audience.members[0].resident_id == synthetic_id("resident-19")


@pytest.mark.asyncio
async def test_resolve_is_idempotent_by_operation_key() -> None:
    audience_service, repository = service()
    context = FakeContext(HOUSE_ONE)
    scope = AudienceScope(kind=ScopeKind.FLOOR, entrance=2, floor=5)

    first = await audience_service.resolve(scope, context, operation_key="same-command")
    repeated = await audience_service.resolve(scope, context, operation_key="same-command")

    assert first == repeated
    assert len(repository.by_id) == 1


@pytest.mark.asyncio
async def test_reused_operation_key_with_new_scope_is_a_conflict() -> None:
    audience_service, repository = service()
    context = FakeContext(HOUSE_ONE)
    await audience_service.resolve(
        AudienceScope(kind=ScopeKind.FLOOR, entrance=2, floor=5),
        context,
        operation_key="same-command",
    )

    with pytest.raises(ValueError, match="operation key conflicts"):
        await audience_service.resolve(
            AudienceScope(kind=ScopeKind.ENTRANCE, entrance=2),
            context,
            operation_key="same-command",
        )
    assert len(repository.by_id) == 1


@pytest.mark.asyncio
async def test_changed_scope_creates_new_revision_without_mutating_previous() -> None:
    audience_service, repository = service()
    context = FakeContext(HOUSE_ONE)
    first = await audience_service.resolve(
        AudienceScope(kind=ScopeKind.FLOOR, entrance=2, floor=5),
        context,
        operation_key="first",
    )

    changed = await audience_service.resolve(
        AudienceScope(kind=ScopeKind.RISER, riser_id=RISER_E2_A, riser_kind="cold_water"),
        context,
        operation_key="changed",
        supersedes_id=first.audience_id,
    )

    assert changed.criteria_revision == 2
    assert changed.supersedes_id == first.audience_id
    assert changed.eligible_count == 6
    assert repository.by_id[first.audience_id].eligible_count == 12


@pytest.mark.asyncio
async def test_previous_audience_cannot_get_two_competing_successors() -> None:
    audience_service, repository = service()
    context = FakeContext(HOUSE_ONE)
    first = await audience_service.resolve(
        AudienceScope(kind=ScopeKind.HOUSE), context, operation_key="first"
    )
    await audience_service.resolve(
        AudienceScope(kind=ScopeKind.ENTRANCE, entrance=2),
        context,
        operation_key="second",
        supersedes_id=first.audience_id,
    )

    with pytest.raises(ValueError, match="already superseded"):
        await audience_service.resolve(
            AudienceScope(kind=ScopeKind.FLOOR, entrance=2, floor=5),
            context,
            operation_key="third",
            supersedes_id=first.audience_id,
        )
    assert len(repository.by_id) == 2


@pytest.mark.asyncio
async def test_scope_cannot_supersede_audience_of_another_house() -> None:
    audience_service, repository = service()
    first = await audience_service.resolve(
        AudienceScope(kind=ScopeKind.HOUSE),
        FakeContext(HOUSE_TWO),
        operation_key="other",
    )

    with pytest.raises(ValueError, match="another house"):
        await audience_service.resolve(
            AudienceScope(kind=ScopeKind.HOUSE),
            FakeContext(HOUSE_ONE),
            operation_key="wrong-house",
            supersedes_id=first.audience_id,
        )
    assert len(repository.by_id) == 1


@pytest.mark.parametrize(
    ("kind", "entrance", "floor", "riser_id", "riser_kind"),
    [
        (ScopeKind.ENTRANCE, None, None, None, None),
        (ScopeKind.FLOOR, None, 5, None, None),
        (ScopeKind.RISER, None, None, RISER_E2_A, None),
        (ScopeKind.HOUSE, 2, None, None, None),
        (ScopeKind.ENTRANCE, 0, None, None, None),
    ],
)
def test_scope_requires_explicit_location(
    kind: ScopeKind,
    entrance: int | None,
    floor: int | None,
    riser_id: UUID | None,
    riser_kind: str | None,
) -> None:
    with pytest.raises(ValueError):
        AudienceScope(
            kind=kind,
            entrance=entrance,
            floor=floor,
            riser_id=riser_id,
            riser_kind=riser_kind,
        )


@pytest.mark.asyncio
async def test_wrong_riser_kind_does_not_select_residents() -> None:
    audience_service, _ = service()

    audience = await audience_service.resolve(
        AudienceScope(kind=ScopeKind.RISER, riser_id=RISER_E2_A, riser_kind="heating"),
        FakeContext(HOUSE_ONE),
        operation_key="wrong-riser-kind",
    )

    assert audience.eligible_count == 0
