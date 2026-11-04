from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.core.errors import Conflict, Unauthorized
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.modules.auth.deps import CurrentUser, SessionDep

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(max_length=255)  # no format validation on login: only exact match matters
    password: str = Field(max_length=128)


class RegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: Literal["user", "admin"]


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


def _token(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.role),
        user=UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role),  # type: ignore[arg-type]
    )


@router.post("/login")
async def login(body: LoginIn, session: SessionDep) -> TokenOut:
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise Unauthorized("Email hoặc mật khẩu không đúng")
    return _token(user)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, session: SessionDep) -> TokenOut:
    exists = await session.scalar(select(User.id).where(func.lower(User.email) == body.email.lower()))
    if exists:
        raise Conflict("Email đã được sử dụng")
    user = User(
        email=body.email.lower(),
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role="user",
    )
    session.add(user)
    await session.commit()
    return _token(user)


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role)  # type: ignore[arg-type]
