from fastapi import APIRouter, status

from app.modules.auth.deps import CurrentUser, SessionDep
from app.modules.queries import service
from app.modules.queries.schemas import ApproveIn, EditIn, FeedbackIn, QueryRunOut

router = APIRouter(prefix="/queries", tags=["queries"])


async def _out(session: SessionDep, user: CurrentUser, run_id: int) -> QueryRunOut:
    run = await service.get_owned_run(session, user, run_id)
    feedback = await service.feedback_map(session, user.id, [run.id])
    return QueryRunOut.build(run, feedback.get(run.id))


@router.get("/{run_id}")
async def get_run(run_id: int, user: CurrentUser, session: SessionDep) -> QueryRunOut:
    return await _out(session, user, run_id)


@router.post("/{run_id}/approve")
async def approve(run_id: int, body: ApproveIn, user: CurrentUser, session: SessionDep) -> QueryRunOut:
    await service.approve(session, user, run_id, body.sql_hash)
    return await _out(session, user, run_id)


@router.post("/{run_id}/edit")
async def edit(run_id: int, body: EditIn, user: CurrentUser, session: SessionDep) -> QueryRunOut:
    await service.edit(session, user, run_id, body.sql)
    return await _out(session, user, run_id)


@router.post("/{run_id}/cancel")
async def cancel(run_id: int, user: CurrentUser, session: SessionDep) -> QueryRunOut:
    await service.cancel(session, user, run_id)
    return await _out(session, user, run_id)


@router.put("/{run_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def feedback(run_id: int, body: FeedbackIn, user: CurrentUser, session: SessionDep) -> None:
    await service.give_feedback(session, user, run_id, body.rating, body.comment)
