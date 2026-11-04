from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.core.errors import AppError, Conflict, NotFound
from app.db.models import AccessRequest, Entitlement, User
from app.modules.access.service import can_access
from app.modules.auth.deps import AdminUser, CurrentUser, SessionDep
from app.observability.audit import audit
from app.semantic.registry import get_registry

router = APIRouter(tags=["access"])


class AccessRequestIn(BaseModel):
    dataset_code: str
    reason: str = Field(min_length=10, max_length=1000)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=1000)
    expires_at: datetime | None = None


class AccessRequestOut(BaseModel):
    id: int
    dataset_code: str
    dataset_name: str
    reason: str
    status: str
    requester_email: str | None = None
    requester_name: str | None = None
    reviewer_name: str | None = None
    review_comment: str | None
    expires_at: datetime | None
    created_at: datetime
    reviewed_at: datetime | None


class EntitlementOut(BaseModel):
    id: int
    user_email: str
    user_name: str
    dataset_code: str
    dataset_name: str
    granted_at: datetime
    expires_at: datetime | None


def _dataset_name(code: str) -> str:
    dataset = get_registry().get(code)
    return dataset.name if dataset else code


def _out(r: AccessRequest, requester: User | None = None, reviewer: User | None = None) -> AccessRequestOut:
    return AccessRequestOut(
        id=r.id,
        dataset_code=r.dataset_code,
        dataset_name=_dataset_name(r.dataset_code),
        reason=r.reason,
        status=r.status,
        requester_email=requester.email if requester else None,
        requester_name=requester.full_name if requester else None,
        reviewer_name=reviewer.full_name if reviewer else None,
        review_comment=r.review_comment,
        expires_at=r.expires_at,
        created_at=r.created_at,
        reviewed_at=r.reviewed_at,
    )


# ---------------------------------------------------------------------------------------------- user


@router.post("/access-requests", status_code=status.HTTP_201_CREATED)
async def create_request(body: AccessRequestIn, user: CurrentUser, session: SessionDep) -> AccessRequestOut:
    registry = get_registry()
    dataset = registry.get(body.dataset_code)
    if dataset is None:
        raise NotFound("Dataset không tồn tại")
    if await can_access(session, user, registry, dataset.code):
        raise Conflict("Bạn đã có quyền truy cập dataset này")
    pending = await session.scalar(
        select(AccessRequest.id).where(
            AccessRequest.user_id == user.id,
            AccessRequest.dataset_code == dataset.code,
            AccessRequest.status == "pending",
        )
    )
    if pending:
        raise Conflict("Bạn đã có một yêu cầu đang chờ duyệt cho dataset này")
    request = AccessRequest(user_id=user.id, dataset_code=dataset.code, reason=body.reason)
    session.add(request)
    await session.flush()
    audit(session, actor_id=user.id, action="access.requested", entity="access_request", entity_id=request.id,
          dataset=dataset.code)  # fmt: skip
    await session.commit()
    await session.refresh(request)
    return _out(request)


@router.get("/access-requests")
async def my_requests(user: CurrentUser, session: SessionDep) -> list[AccessRequestOut]:
    reviewer = aliased(User)
    rows = await session.execute(
        select(AccessRequest, reviewer)
        .outerjoin(reviewer, reviewer.id == AccessRequest.reviewer_id)
        .where(AccessRequest.user_id == user.id)
        .order_by(AccessRequest.created_at.desc())
    )
    return [_out(r, reviewer=rv) for r, rv in rows.all()]


@router.post("/access-requests/{request_id}/cancel")
async def cancel_request(request_id: int, user: CurrentUser, session: SessionDep) -> AccessRequestOut:
    request = await session.get(AccessRequest, request_id)
    if request is None or request.user_id != user.id:
        raise NotFound("Không tìm thấy yêu cầu")
    if request.status != "pending":
        raise Conflict("Chỉ hủy được yêu cầu đang chờ duyệt")
    request.status = "cancelled"
    audit(session, actor_id=user.id, action="access.cancelled", entity="access_request", entity_id=request.id)
    await session.commit()
    return _out(request)


# --------------------------------------------------------------------------------------------- admin


@router.get("/admin/access-requests")
async def list_requests(_: AdminUser, session: SessionDep, status: str = "pending") -> list[AccessRequestOut]:
    requester, reviewer = aliased(User), aliased(User)
    query = (
        select(AccessRequest, requester, reviewer)
        .join(requester, requester.id == AccessRequest.user_id)
        .outerjoin(reviewer, reviewer.id == AccessRequest.reviewer_id)
        .order_by(AccessRequest.created_at.desc())
        .limit(200)
    )
    if status != "all":
        query = query.where(AccessRequest.status == status)
    rows = await session.execute(query)
    return [_out(r, rq, rv) for r, rq, rv in rows.all()]


@router.post("/admin/access-requests/{request_id}/decision")
async def decide(
    request_id: int, body: DecisionIn, admin: AdminUser, session: SessionDep
) -> AccessRequestOut:
    request = await session.get(AccessRequest, request_id, with_for_update=True)
    if request is None:
        raise NotFound("Không tìm thấy yêu cầu")
    if request.status != "pending":
        raise Conflict("Yêu cầu đã được xử lý")
    if request.user_id == admin.id:
        raise AppError("Không thể tự duyệt yêu cầu của chính mình", code="self_review")
    if body.decision == "reject" and not (body.comment and body.comment.strip()):
        raise AppError("Cần nêu lý do khi từ chối", code="comment_required")

    now = datetime.now(UTC)
    request.status = "approved" if body.decision == "approve" else "rejected"
    request.reviewer_id = admin.id
    request.review_comment = body.comment
    request.reviewed_at = now
    request.expires_at = body.expires_at
    if body.decision == "approve":
        stmt = insert(Entitlement).values(
            user_id=request.user_id,
            dataset_code=request.dataset_code,
            granted_by=admin.id,
            granted_at=now,
            expires_at=body.expires_at,
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Entitlement.user_id, Entitlement.dataset_code],
                set_={
                    "granted_by": admin.id,
                    "granted_at": now,
                    "expires_at": body.expires_at,
                    "revoked_at": None,
                },
            )
        )
    audit(session, actor_id=admin.id, action=f"access.{request.status}", entity="access_request",
          entity_id=request.id, dataset=request.dataset_code, user_id=request.user_id)  # fmt: skip
    await session.commit()
    requester = await session.get(User, request.user_id)
    return _out(request, requester, admin)


@router.get("/admin/entitlements")
async def list_entitlements(_: AdminUser, session: SessionDep) -> list[EntitlementOut]:
    rows = await session.execute(
        select(Entitlement, User)
        .join(User, User.id == Entitlement.user_id)
        .where(Entitlement.revoked_at.is_(None))
        .order_by(Entitlement.granted_at.desc())
    )
    return [
        EntitlementOut(
            id=e.id,
            user_email=u.email,
            user_name=u.full_name,
            dataset_code=e.dataset_code,
            dataset_name=_dataset_name(e.dataset_code),
            granted_at=e.granted_at,
            expires_at=e.expires_at,
        )
        for e, u in rows.all()
    ]


@router.delete("/admin/entitlements/{entitlement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke(entitlement_id: int, admin: AdminUser, session: SessionDep) -> None:
    entitlement = await session.get(Entitlement, entitlement_id)
    if entitlement is None or entitlement.revoked_at is not None:
        raise NotFound("Không tìm thấy quyền")
    entitlement.revoked_at = datetime.now(UTC)
    audit(session, actor_id=admin.id, action="access.revoked", entity="entitlement", entity_id=entitlement.id,
          dataset=entitlement.dataset_code, user_id=entitlement.user_id)  # fmt: skip
    await session.commit()
