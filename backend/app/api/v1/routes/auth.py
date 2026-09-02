from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth_dependency import ProductPrincipalDep
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (
    AccountActionRead,
    AuthSessionRead,
    ChangePasswordRequest,
    EmailVerificationCompleteRequest,
    LoginRequest,
    PasswordResetCompleteRequest,
    PasswordResetRequest,
    RegisterRequest,
    SessionRevocationRead,
)
from app.services.account_action_service import (
    EMAIL_VERIFICATION,
    PASSWORD_RESET,
    find_active_user_by_email,
    issue_account_action_token,
    reset_password_with_token,
    verify_email_with_token,
)
from app.services.account_email_service import (
    AccountEmailDeliveryError,
    AccountEmailSender,
    AccountEmailSenderDep,
)
from app.services.demo_auth_service import (
    SESSION_COOKIE_NAME,
    create_session_token,
    credentials_are_valid,
    read_session_token,
)
from app.services.login_throttle_service import LoginThrottleService
from app.services.user_auth_service import (
    DuplicateEmailError,
    change_password,
    login_user,
    read_session,
    register_user,
    revoke_other_sessions,
    revoke_session,
)

router = APIRouter(prefix="/auth")
SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[Session, Depends(get_db)]


def _send_password_reset_safely(
    email_sender: AccountEmailSender,
    recipient: str,
    token: str,
) -> None:
    try:
        email_sender.send_password_reset(recipient, token)
    except AccountEmailDeliveryError:
        return


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


def _principal_response(principal, *, registration_enabled: bool) -> AuthSessionRead:
    return AuthSessionRead(
        enabled=True,
        authenticated=True,
        username=principal.email,
        email=principal.email,
        user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        auth_mode="user",
        registration_enabled=registration_enabled,
        email_verified=principal.email_verified,
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
            return AuthSessionRead(
                enabled=True,
                authenticated=False,
                auth_mode="user",
                registration_enabled=settings.allow_public_registration,
            )
        return _principal_response(
            principal,
            registration_enabled=settings.allow_public_registration,
        )
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
    return _principal_response(
        principal,
        registration_enabled=settings.allow_public_registration,
    )


@router.post(
    "/login",
    response_model=AuthSessionRead,
    response_model_exclude_unset=True,
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    db: DbSession,
) -> AuthSessionRead:
    if settings.enable_user_auth:
        throttle = LoginThrottleService(
            db,
            max_failures=settings.user_auth_login_max_failures,
            window_seconds=settings.user_auth_login_window_seconds,
            lock_seconds=settings.user_auth_login_lock_seconds,
        )
        remote_address = request.client.host if request.client is not None else None
        decision = throttle.check(payload.username, remote_address)
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="登录尝试过多，请稍后再试。",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        authenticated = login_user(
            db,
            email=payload.username,
            password=payload.password,
            session_ttl_seconds=settings.user_auth_session_ttl_seconds,
        )
        if authenticated is None:
            decision = throttle.record_failure(payload.username, remote_address)
            db.commit()
            if not decision.allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="登录尝试过多，请稍后再试。",
                    headers={"Retry-After": str(decision.retry_after_seconds)},
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="账号或密码不正确。",
            )
        principal, token = authenticated
        throttle.clear(payload.username, remote_address)
        db.commit()
        _set_session_cookie(
            response,
            token=token,
            max_age=settings.user_auth_session_ttl_seconds,
            secure=settings.user_auth_cookie_secure,
            same_site="lax",
        )
        return _principal_response(
            principal,
            registration_enabled=settings.allow_public_registration,
        )
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
    "/change-password",
    response_model=AuthSessionRead,
    response_model_exclude_unset=True,
)
def update_password(
    payload: ChangePasswordRequest,
    response: Response,
    settings: SettingsDep,
    db: DbSession,
    principal: ProductPrincipalDep,
) -> AuthSessionRead:
    try:
        token = change_password(
            db,
            user_id=principal.user_id,
            current_password=payload.current_password,
            new_password=payload.new_password,
            session_ttl_seconds=settings.user_auth_session_ttl_seconds,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="新密码不能与当前密码相同。",
        ) from exc
    if token is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="当前密码不正确。",
        )
    db.commit()
    _set_session_cookie(
        response,
        token=token,
        max_age=settings.user_auth_session_ttl_seconds,
        secure=settings.user_auth_cookie_secure,
        same_site="lax",
    )
    return _principal_response(
        principal,
        registration_enabled=settings.allow_public_registration,
    )


@router.post("/sessions/revoke-others", response_model=SessionRevocationRead)
def logout_other_devices(
    settings: SettingsDep,
    db: DbSession,
    principal: ProductPrincipalDep,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> SessionRevocationRead:
    if not settings.enable_user_auth or session_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    revoked = revoke_other_sessions(
        db,
        user_id=principal.user_id,
        token=session_token,
    )
    db.commit()
    return SessionRevocationRead(revoked_sessions=revoked)


@router.post(
    "/password-reset/request",
    response_model=AccountActionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_password_reset(
    payload: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    db: DbSession,
    email_sender: AccountEmailSenderDep,
) -> AccountActionRead:
    generic = AccountActionRead(
        message="如果该邮箱已注册且邮件服务可用，我们会发送密码重置链接。"
    )
    if not settings.enable_user_auth:
        return generic
    user = find_active_user_by_email(db, payload.email)
    if user is None or not email_sender.configured:
        return generic
    token = issue_account_action_token(
        db,
        user_id=user.id,
        purpose=PASSWORD_RESET,
        ttl_seconds=settings.password_reset_token_ttl_seconds,
        cooldown_seconds=settings.account_email_request_cooldown_seconds,
    )
    if token is None:
        db.rollback()
        return generic
    db.commit()
    background_tasks.add_task(
        _send_password_reset_safely,
        email_sender,
        user.email,
        token,
    )
    return generic


@router.post(
    "/password-reset/complete",
    response_model=AccountActionRead,
)
def complete_password_reset(
    payload: PasswordResetCompleteRequest,
    response: Response,
    settings: SettingsDep,
    db: DbSession,
) -> AccountActionRead:
    if not settings.enable_user_auth:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前环境未启用用户账号。",
        )
    result = reset_password_with_token(
        db,
        token=payload.token,
        new_password=payload.new_password,
    )
    if result == "INVALID":
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="重置链接无效或已过期，请重新申请。",
        )
    if result == "UNCHANGED":
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="新密码不能与当前密码相同。",
        )
    db.commit()
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.user_auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    return AccountActionRead(message="密码已重置，请使用新密码登录。")


@router.post(
    "/email-verification/request",
    response_model=AccountActionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_email_verification(
    settings: SettingsDep,
    db: DbSession,
    principal: ProductPrincipalDep,
    email_sender: AccountEmailSenderDep,
) -> AccountActionRead:
    user = db.get(User, principal.user_id)
    if user is None or user.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if user.email_verified_at is not None:
        return AccountActionRead(message="邮箱已经验证，无需重复操作。")
    if not email_sender.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="系统邮件服务尚未配置，请联系管理员。",
        )
    token = issue_account_action_token(
        db,
        user_id=user.id,
        purpose=EMAIL_VERIFICATION,
        ttl_seconds=settings.email_verification_token_ttl_seconds,
        cooldown_seconds=settings.account_email_request_cooldown_seconds,
    )
    if token is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="验证邮件已发送，请稍后再试。",
            headers={
                "Retry-After": str(settings.account_email_request_cooldown_seconds)
            },
        )
    try:
        email_sender.send_email_verification(user.email, token)
    except AccountEmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="验证邮件发送失败，请稍后重试。",
        ) from exc
    db.commit()
    return AccountActionRead(message="验证邮件已发送，请前往邮箱完成验证。")


@router.post(
    "/email-verification/complete",
    response_model=AccountActionRead,
)
def complete_email_verification(
    payload: EmailVerificationCompleteRequest,
    settings: SettingsDep,
    db: DbSession,
) -> AccountActionRead:
    if not settings.enable_user_auth:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前环境未启用用户账号。",
        )
    if not verify_email_with_token(db, payload.token):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证链接无效或已过期，请重新申请。",
        )
    db.commit()
    return AccountActionRead(message="邮箱验证成功，现在可以返回工作台。")


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
