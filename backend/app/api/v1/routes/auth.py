from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.auth import AuthSessionRead, LoginRequest, RegisterRequest
from app.services.demo_auth_service import (
    SESSION_COOKIE_NAME,
    create_session_token,
    credentials_are_valid,
    read_session_token,
)
from app.services.user_auth_service import (
    DuplicateEmailError,
    login_user,
    read_session,
    register_user,
    revoke_session,
)

router = APIRouter(prefix="/auth")
SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[Session, Depends(get_db)]


def _set_session_cookie(
    response: Response,
    *,
    token: str,
    max_age: int,
    secure: bool,
    same_site: str,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite=same_site,
        path="/",
    )


def _principal_response(principal) -> AuthSessionRead:
    return AuthSessionRead(
        enabled=True,
        authenticated=True,
        username=principal.email,
        email=principal.email,
        user_id=principal.user_id,
        workspace_id=principal.workspace_id,
    )


@router.get(
    "/session",
    response_model=AuthSessionRead,
    response_model_exclude_unset=True,
)
def get_auth_session(
    settings: SettingsDep,
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> AuthSessionRead:
    if settings.enable_user_auth:
        principal = read_session(db, session_token)
        if principal is None:
            return AuthSessionRead(enabled=True, authenticated=False)
        return _principal_response(principal)
    if not settings.enable_demo_auth:
        return AuthSessionRead(enabled=False, authenticated=True, username=None)
    user = read_session_token(settings, session_token)
    return AuthSessionRead(
        enabled=True,
        authenticated=user is not None,
        username=user.username if user is not None else None,
    )


@router.post(
    "/register",
    response_model=AuthSessionRead,
    response_model_exclude_unset=True,
    status_code=201,
)
def register(
    payload: RegisterRequest,
    response: Response,
    settings: SettingsDep,
    db: DbSession,
) -> AuthSessionRead:
    if not settings.enable_user_auth or not settings.allow_public_registration:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前环境未开放用户注册。",
        )
    try:
        principal, token = register_user(
            db,
            email=payload.email,
            password=payload.password,
            workspace_name=payload.workspace_name,
            session_ttl_seconds=settings.user_auth_session_ttl_seconds,
        )
        db.commit()
    except DuplicateEmailError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已注册。",
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已注册。",
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="注册信息无效。",
        ) from exc
    _set_session_cookie(
        response,
        token=token,
        max_age=settings.user_auth_session_ttl_seconds,
        secure=settings.user_auth_cookie_secure,
        same_site="lax",
    )
    return _principal_response(principal)


@router.post(
    "/login",
    response_model=AuthSessionRead,
    response_model_exclude_unset=True,
)
def login(
    payload: LoginRequest,
    response: Response,
    settings: SettingsDep,
    db: DbSession,
) -> AuthSessionRead:
    if settings.enable_user_auth:
        authenticated = login_user(
            db,
            email=payload.username,
            password=payload.password,
            session_ttl_seconds=settings.user_auth_session_ttl_seconds,
        )
        if authenticated is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="账号或密码不正确。",
            )
        principal, token = authenticated
        db.commit()
        _set_session_cookie(
            response,
            token=token,
            max_age=settings.user_auth_session_ttl_seconds,
            secure=settings.user_auth_cookie_secure,
            same_site="lax",
        )
        return _principal_response(principal)
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
    _set_session_cookie(
        response,
        token=create_session_token(settings, username),
        max_age=settings.demo_auth_session_ttl_seconds,
        secure=settings.demo_auth_cookie_secure,
        same_site="strict",
    )
    return AuthSessionRead(enabled=True, authenticated=True, username=username)


@router.post(
    "/logout",
    response_model=AuthSessionRead,
    response_model_exclude_unset=True,
)
def logout(
    response: Response,
    settings: SettingsDep,
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> AuthSessionRead:
    if settings.enable_user_auth:
        revoke_session(db, session_token)
        db.commit()
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=(
            settings.user_auth_cookie_secure
            if settings.enable_user_auth
            else settings.demo_auth_cookie_secure
        ),
        samesite="lax" if settings.enable_user_auth else "strict",
        path="/",
    )
    return AuthSessionRead(
        enabled=settings.enable_user_auth or settings.enable_demo_auth,
        authenticated=not settings.enable_user_auth and not settings.enable_demo_auth,
    )
