"""Жизненный цикл async engine и транзакционная Unit of Work."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(database_url: str) -> AsyncEngine:
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL must use postgresql+asyncpg")
    return create_async_engine(database_url, pool_pre_ping=True)


class SqlUnitOfWork:
    """Одна новая session на use case; commit явный, иначе rollback при выходе."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions
        self.session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        self.session = self.sessions()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if self.session is None:
            return False
        if exc_type is not None or not self._committed:
            await self.session.rollback()
        await self.session.close()
        self.session = None
        return False

    async def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work is not active")
        await self.session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work is not active")
        await self.session.rollback()


@asynccontextmanager
async def database_lifespan(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine(database_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
