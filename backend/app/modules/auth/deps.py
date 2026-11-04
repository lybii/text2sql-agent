from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_session

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise Unauthorized("Bạn cần đăng nhập")
    user = await session.get(User, decode_access_token(credentials.credentials))
    if user is None or not user.is_active:
        raise Unauthorized("Tài khoản không tồn tại hoặc đã bị khóa")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise Forbidden("Chỉ quản trị viên được thực hiện thao tác này")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
