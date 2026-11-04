from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent


def audit(
    session: AsyncSession,
    *,
    actor_id: int | None,
    action: str,
    entity: str,
    entity_id: int | None,
    **detail: Any,
) -> None:
    """Queue an append-only audit row in the caller's transaction (committed together with the change)."""
    session.add(
        AuditEvent(actor_id=actor_id, action=action, entity=entity, entity_id=entity_id, detail=detail)
    )
