from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status

from app.core.config import Settings, get_settings
from app.services.demo_auth_service import (
    SESSION_COOKIE_NAME,
    AuthenticatedUser,
    read_session_token,
)

SettingsDep = Annotated[Settings, Depends(get_settings)]


def require_authenticated_user(
    settings: SettingsDep,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> AuthenticatedUser | None:
    if not settings.enable_demo_auth:
        return None
    user = read_session_token(settings, session_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录后再使用工作台。",
        )
    return user
