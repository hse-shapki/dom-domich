"""Серверное хранилище коротких непрозрачных callback actions."""

import hashlib
import secrets
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.application.polls.callback import StoredPollAction
from dom_domych.domain.polls.models import VoteChoice
from dom_domych.infrastructure.postgres.models import PollActionRow


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PostgresPollActionStore:
    """Raw token возвращается только при выпуске; в БД остаётся SHA-256 digest."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, action: StoredPollAction) -> str:
        token = secrets.token_urlsafe(24)
        self.session.add(
            PollActionRow(
                token_digest=token_digest(token),
                poll_id=action.poll_id,
                house_id=action.house_id,
                audience_id=action.audience_id,
                subject_revision=action.subject_revision,
                choice=action.choice.value,
                expires_at=action.expires_at,
                bound_resident_id=action.bound_resident_id,
                revoked=action.revoked,
            )
        )
        await self.session.flush()
        return token

    async def get(self, token: str) -> StoredPollAction | None:
        if not token or len(token) > 1024:
            return None
        row = await self.session.scalar(
            select(PollActionRow).where(PollActionRow.token_digest == token_digest(token))
        )
        if row is None:
            return None
        return StoredPollAction(
            poll_id=row.poll_id,
            house_id=row.house_id,
            audience_id=row.audience_id,
            subject_revision=row.subject_revision,
            choice=VoteChoice(row.choice),
            expires_at=row.expires_at,
            bound_resident_id=row.bound_resident_id,
            revoked=row.revoked,
        )

    async def revoke_poll(self, poll_id: UUID, house_id: UUID) -> None:
        await self.session.execute(
            update(PollActionRow)
            .where(PollActionRow.poll_id == poll_id, PollActionRow.house_id == house_id)
            .values(revoked=True)
        )
