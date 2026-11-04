from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def app_engine() -> AsyncEngine:
    """Engine for the `app_backend` role: read/write on schema `app` only."""
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def analytics_engine() -> AsyncEngine:
    """Engine for the `analytics_reader` role: SELECT on schema `analytics` only."""
    return create_async_engine(get_settings().analytics_database_url, pool_pre_ping=True, pool_size=5)


@lru_cache
def session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


async def dispose_engines() -> None:
    for factory in (app_engine, analytics_engine):
        if factory.cache_info().currsize:
            await factory().dispose()
