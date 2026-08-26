from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from app.core.config import Settings, get_settings
from app.schemas.auth import AuthSessionRead, LoginRequest
from app.services.demo_auth_service import (
    SESSION_COOKIE_NAME,
    create_session_token,
    credentials_are_valid,
    read_session_token,
)

router = APIRouter(prefix="/auth")
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/session", response_model=AuthSessionRead)
def get_auth_session(
    settings: SettingsDep,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> AuthSessionRead:
    if not settings.enable_demo_auth:
        return AuthSessionRead(enabled=False, authenticated=True)
    user = read_session_token(settings, session_token)
    return AuthSessionRead(
        enabled=True,
        authenticated=user is not None,
        username=user.username if user is not None else None,
    )


@router.post("/login", response_model=AuthSessionRead)
def login(
    payload: LoginRequest, response: Response, settings: SettingsDep
) -> AuthSessionRead:
    if not settings.enable_demo_auth:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前环境未启用账号登录。",
        )
    if not credentials_are_valid(settings, payload.username, payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码不正确。",
        )
    username = (settings.demo_auth_username or "").strip()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(settings, username),
        max_age=settings.demo_auth_session_ttl_seconds,
        httponly=True,
        secure=settings.demo_auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    return AuthSessionRead(enabled=True, authenticated=True, username=username)


@router.post("/logout", response_model=AuthSessionRead)
def logout(response: Response, settings: SettingsDep) -> AuthSessionRead:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.demo_auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    return AuthSessionRead(
        enabled=settings.enable_demo_auth,
        authenticated=not settings.enable_demo_auth,
    )
