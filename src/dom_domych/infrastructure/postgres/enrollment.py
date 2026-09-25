"""PostgreSQL adapter приглашений, MAX identity и выбора дома."""

import hashlib
import secrets
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.application.residents.enrollment import (
    EnrollmentDenied,
    EnrollmentResult,
    HouseSelection,
)
from dom_domych.infrastructure.postgres.models import (
    ApartmentRow,
    DemoInvitationRow,
    HouseRow,
    ResidencyRow,
    ResidentRow,
)


class PostgresEnrollment:
    """Все команды используют session текущей UoW; токен хранится только как digest."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def issue_invitation(
        self, residency_id: UUID, house_id: UUID, expires_at: datetime, now: datetime
    ) -> str:
        residency = await self.session.scalar(
            select(ResidencyRow).where(
                ResidencyRow.id == residency_id,
                ResidencyRow.house_id == house_id,
                ResidencyRow.valid_from <= now,
                or_(ResidencyRow.valid_until.is_(None), ResidencyRow.valid_until > now),
            )
        )
        if residency is None:
            raise EnrollmentDenied("residency not active in operator house")
        token = secrets.token_urlsafe(24)
        self.session.add(
            DemoInvitationRow(
                token_digest=hashlib.sha256(token.encode()).hexdigest(),
                residency_id=residency_id,
                house_id=house_id,
                expires_at=expires_at,
            )
        )
        await self.session.flush()
        return token

    async def redeem_invitation(
        self, token: str, max_user_id: str, now: datetime
    ) -> EnrollmentResult:
        digest = hashlib.sha256(token.encode()).hexdigest()
        invitation = await self.session.scalar(
            select(DemoInvitationRow)
            .where(DemoInvitationRow.token_digest == digest)
            .with_for_update()
        )
        if invitation is None or now >= invitation.expires_at:
            raise EnrollmentDenied("invitation missing or expired")
        residency = await self.session.scalar(
            select(ResidencyRow).where(ResidencyRow.id == invitation.residency_id).with_for_update()
        )
        if (
            residency is None
            or residency.house_id != invitation.house_id
            or residency.valid_from > now
            or residency.valid_until is not None
            and now >= residency.valid_until
        ):
            raise EnrollmentDenied("residency no longer active")
        resident = await self.session.scalar(
            select(ResidentRow).where(ResidentRow.id == residency.resident_id).with_for_update()
        )
        if resident is None:
            raise EnrollmentDenied("resident not found")
        if invitation.used_at is not None and resident.max_user_id != max_user_id:
            raise EnrollmentDenied("invitation already used")
        if resident.max_user_id is not None and resident.max_user_id != max_user_id:
            raise EnrollmentDenied("resident already linked to another MAX user")
        other_id = await self.session.scalar(
            select(ResidentRow.id).where(ResidentRow.max_user_id == max_user_id)
        )
        if other_id is not None and other_id != resident.id:
            raise EnrollmentDenied("MAX user already linked to another resident")
        apartment = await self.session.scalar(
            select(ApartmentRow).where(
                ApartmentRow.id == residency.apartment_id,
                ApartmentRow.house_id == invitation.house_id,
            )
        )
        if apartment is None:
            raise EnrollmentDenied("apartment not found in house")
        resident.max_user_id = max_user_id
        resident.dm_reachable = True
        if resident.active_house_id is None:
            resident.active_house_id = invitation.house_id
        residency.confirmed = True
        residency.adult = True
        residency.source = "demo_invitation"
        invitation.used_at = now
        return EnrollmentResult(
            resident.id, invitation.house_id, apartment.id, apartment.entrance, apartment.floor
        )

    async def house_selection(self, max_user_id: str, now: datetime) -> HouseSelection:
        resident = await self.session.scalar(
            select(ResidentRow).where(ResidentRow.max_user_id == max_user_id)
        )
        if resident is None:
            return HouseSelection(None, ())
        houses = tuple(
            sorted(
                set(
                    (
                        await self.session.scalars(
                            select(ResidencyRow.house_id).where(
                                ResidencyRow.resident_id == resident.id,
                                ResidencyRow.confirmed.is_(True),
                                ResidencyRow.adult.is_(True),
                                ResidencyRow.valid_from <= now,
                                or_(
                                    ResidencyRow.valid_until.is_(None),
                                    ResidencyRow.valid_until > now,
                                ),
                            )
                        )
                    ).all()
                ),
                key=lambda item: item.bytes,
            )
        )
        selected = resident.active_house_id if resident.active_house_id in houses else None
        if selected is None and len(houses) == 1:
            selected = houses[0]
        return HouseSelection(selected, houses)

    async def select_house(self, max_user_id: str, house_id: UUID, now: datetime) -> None:
        selection = await self.house_selection(max_user_id, now)
        if house_id not in selection.available_house_ids:
            raise EnrollmentDenied("resident has no confirmed active apartment in house")
        await self.session.execute(
            update(ResidentRow)
            .where(ResidentRow.max_user_id == max_user_id)
            .values(active_house_id=house_id)
        )

    async def set_dm_reachable(self, max_user_id: str, reachable: bool) -> bool:
        resident = await self.session.scalar(
            select(ResidentRow).where(ResidentRow.max_user_id == max_user_id).with_for_update()
        )
        if resident is None:
            return False
        resident.dm_reachable = reachable
        return True

    async def bind_house_chat(self, house_id: UUID, max_chat_id: str) -> None:
        house = await self.session.scalar(
            select(HouseRow).where(HouseRow.id == house_id).with_for_update()
        )
        if house is None:
            raise EnrollmentDenied("house not found")
        other = await self.session.scalar(
            select(HouseRow.id).where(HouseRow.max_chat_id == max_chat_id)
        )
        if other is not None and other != house_id:
            raise EnrollmentDenied("MAX chat already linked to another house")
        house.max_chat_id = max_chat_id
