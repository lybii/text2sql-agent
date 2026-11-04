"""Dataset entitlements. Open datasets: every active user. Restricted: an unexpired, unrevoked grant."""

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Entitlement, User
from app.semantic.registry import SemanticRegistry


async def granted_codes(session: AsyncSession, user_id: int) -> set[str]:
    now = datetime.now(UTC)
    rows = await session.scalars(
        select(Entitlement.dataset_code).where(
            Entitlement.user_id == user_id,
            Entitlement.revoked_at.is_(None),
            or_(Entitlement.expires_at.is_(None), Entitlement.expires_at > now),
        )
    )
    return set(rows)


async def accessible_datasets(session: AsyncSession, user: User, registry: SemanticRegistry) -> list[str]:
    granted = await granted_codes(session, user.id)
    return [d.code for d in registry.all() if d.access == "open" or d.code in granted]


async def can_access(session: AsyncSession, user: User, registry: SemanticRegistry, code: str) -> bool:
    dataset = registry.get(code)
    if dataset is None:
        return False
    return dataset.access == "open" or code in await granted_codes(session, user.id)
