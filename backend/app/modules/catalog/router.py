from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import AccessRequest
from app.modules.access.service import granted_codes
from app.modules.auth.deps import CurrentUser, SessionDep
from app.semantic.registry import get_registry

router = APIRouter(prefix="/datasets", tags=["catalog"])

AccessStatus = Literal["open", "granted", "pending", "none"]


class MetricOut(BaseModel):
    code: str
    name: str
    description: str
    unit: str


class ColumnOut(BaseModel):
    name: str
    type: str
    description: str


class TableOut(BaseModel):
    name: str
    description: str
    columns: list[ColumnOut]


class DatasetOut(BaseModel):
    code: str
    name: str
    description: str
    owner: str
    access: Literal["open", "restricted"]
    sensitivity: str
    access_status: AccessStatus
    metrics: list[MetricOut]
    dimensions: list[str]
    sample_questions: list[str]
    tables: list[TableOut]  # column-level metadata only when the user can access the dataset


@router.get("")
async def list_datasets(user: CurrentUser, session: SessionDep) -> list[DatasetOut]:
    granted = await granted_codes(session, user.id)
    pending = set(
        await session.scalars(
            select(AccessRequest.dataset_code).where(
                AccessRequest.user_id == user.id, AccessRequest.status == "pending"
            )
        )
    )
    out = []
    for d in get_registry().all():
        status: AccessStatus = (
            "open"
            if d.access == "open"
            else "granted"
            if d.code in granted
            else "pending"
            if d.code in pending
            else "none"
        )
        visible = status in ("open", "granted")
        out.append(
            DatasetOut(
                code=d.code,
                name=d.name,
                description=d.description,
                owner=d.owner,
                access=d.access,
                sensitivity=d.sensitivity,
                access_status=status,
                metrics=[
                    MetricOut(code=m.code, name=m.name, description=m.description, unit=m.unit)
                    for m in d.metrics
                ],
                dimensions=[dim.name for dim in d.dimensions],
                sample_questions=d.sample_questions,
                tables=[
                    TableOut(
                        name=t.name,
                        description=t.description,
                        columns=[
                            ColumnOut(name=c.name, type=c.type, description=c.description) for c in t.columns
                        ],
                    )
                    for t in d.tables
                ]
                if visible
                else [],
            )
        )
    return out
