from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services.demo_auth_service import (
    SESSION_COOKIE_NAME,
    AuthenticatedUser,
    read_session_token,
)
from app.services.user_auth_service import AuthenticatedPrincipal, read_session

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[Session, Depends(get_db)]


def require_authenticated_user(
    settings: SettingsDep,
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> AuthenticatedPrincipal | AuthenticatedUser | None:
    if settings.enable_user_auth:
        principal = read_session(db, session_token)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="请先登录后再使用工作台。",
            )
        return principal
    if not settings.enable_demo_auth:
        return None
    user = read_session_token(settings, session_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录后再使用工作台。",
        )
    return user


def require_product_principal(
    principal: Annotated[
        AuthenticatedPrincipal | AuthenticatedUser | None,
        Depends(require_authenticated_user),
    ],
) -> AuthenticatedPrincipal:
    if not isinstance(principal, AuthenticatedPrincipal):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前环境尚未启用独立用户账号。",
        )
    return principal


ProductPrincipalDep = Annotated[
    AuthenticatedPrincipal, Depends(require_product_principal)
]
