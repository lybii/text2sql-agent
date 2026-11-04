from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.ratelimit import RateLimiter
from app.db.models import Conversation, Message, QueryRun
from app.modules.auth.deps import CurrentUser, SessionDep
from app.modules.queries import service as queries
from app.modules.queries.schemas import QueryRunOut

router = APIRouter(prefix="/conversations", tags=["conversations"])
_limiter = RateLimiter(get_settings().rate_limit_per_minute)


class ConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    query: QueryRunOut | None = None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class TurnOut(BaseModel):
    messages: list[MessageOut]


async def _owned(session: SessionDep, user: CurrentUser, conversation_id: int) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise NotFound("Không tìm thấy cuộc trò chuyện")
    return conversation


@router.get("")
async def list_conversations(user: CurrentUser, session: SessionDep) -> list[ConversationOut]:
    counts = (
        select(Message.conversation_id, func.count().label("n")).group_by(Message.conversation_id).subquery()
    )
    rows = await session.execute(
        select(Conversation, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.conversation_id == Conversation.id)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    )
    return [
        ConversationOut(
            id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at, message_count=n
        )
        for c, n in rows.all()
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationIn, user: CurrentUser, session: SessionDep
) -> ConversationOut:
    conversation = Conversation(user_id=user.id, title=body.title or queries.DEFAULT_TITLE)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: int, user: CurrentUser, session: SessionDep
) -> ConversationDetail:
    conversation = await _owned(session, user, conversation_id)
    rows = await session.execute(
        select(Message, QueryRun)
        .outerjoin(QueryRun, QueryRun.id == Message.query_run_id)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.id)
    )
    pairs = rows.all()
    feedback = await queries.feedback_map(session, user.id, [r.id for _, r in pairs if r is not None])
    messages = [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            # The query card is attached to the assistant reply only.
            query=QueryRunOut.build(r, feedback.get(r.id))
            if r is not None and m.role == "assistant"
            else None,
        )
        for m, r in pairs
    ]
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=len(messages),
        messages=messages,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: int, user: CurrentUser, session: SessionDep) -> None:
    conversation = await _owned(session, user, conversation_id)
    await session.execute(delete(Conversation).where(Conversation.id == conversation.id))
    await session.commit()


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: int, body: MessageIn, user: CurrentUser, session: SessionDep
) -> TurnOut:
    conversation = await _owned(session, user, conversation_id)
    _limiter.check(user.id)
    user_msg, assistant_msg, run = await queries.plan_question(session, user, conversation, body.content)
    await session.refresh(run)
    return TurnOut(
        messages=[
            MessageOut(id=user_msg.id, role="user", content=user_msg.content, created_at=user_msg.created_at),
            MessageOut(
                id=assistant_msg.id,
                role="assistant",
                content=assistant_msg.content,
                created_at=assistant_msg.created_at,
                query=QueryRunOut.build(run),
            ),
        ]
    )
