import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    AccountActionToken,
    AuthSession,
    LoginThrottle,
    Membership,
    User,
    Workspace,
)
from app.services.account_email_service import get_account_email_sender

EMAIL = "owner@example.com"
PASSWORD = "strong-user-password"


class FakeAccountEmailSender:
    configured = True

    def __init__(self) -> None:
        self.password_resets: list[tuple[str, str]] = []
        self.email_verifications: list[tuple[str, str]] = []

    def send_password_reset(self, recipient: str, token: str) -> None:
        self.password_resets.append((recipient, token))

    def send_email_verification(self, recipient: str, token: str) -> None:
        self.email_verifications.append((recipient, token))


def user_auth_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "enable_user_auth": True,
        "allow_public_registration": True,
        "user_auth_session_ttl_seconds": 3600,
        "user_auth_cookie_secure": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_registration_creates_isolated_account_and_secure_session(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()

    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": EMAIL.upper(),
            "password": PASSWORD,
            "workspace_name": "Owner Workspace",
        },
    )
    session = client.get("/api/v1/auth/session")
    protected = client.get("/api/v1/products")

    assert registered.status_code == 201
    payload = registered.json()
    assert payload["enabled"] is True
    assert payload["authenticated"] is True
    assert payload["email"] == EMAIL
    assert payload["username"] == EMAIL
    assert payload["user_id"] > 0
    assert payload["workspace_id"] > 0
    assert payload["auth_mode"] == "user"
    assert payload["registration_enabled"] is True
    assert payload["email_verified"] is False
    assert session.json() == payload
    assert protected.status_code == 200

    cookie = registered.headers["set-cookie"]
    token = registered.cookies.get("socialpilot_session")
    assert token is not None
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert PASSWORD not in cookie

    user = db_session.scalar(select(User).where(User.email == EMAIL))
    auth_session = db_session.scalar(select(AuthSession))
    assert user is not None
    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert auth_session is not None
    assert auth_session.token_hash != token
    assert token not in auth_session.token_hash
    assert db_session.scalar(select(Workspace)) is not None
    assert db_session.scalar(select(Membership)) is not None


def test_logout_revokes_session_and_login_restores_access(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"email": EMAIL, "password": PASSWORD},
        ).status_code
        == 201
    )

    logged_out = client.post("/api/v1/auth/logout")
    revoked_session = db_session.scalar(select(AuthSession))
    blocked = client.get("/api/v1/products")
    wrong = client.post(
        "/api/v1/auth/login",
        json={"username": EMAIL, "password": "wrong-password"},
    )
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"username": EMAIL.upper(), "password": PASSWORD},
    )
    restored = client.get("/api/v1/products")

    assert logged_out.status_code == 200
    assert revoked_session is not None
    assert revoked_session.revoked_at is not None
    assert blocked.status_code == 401
    assert wrong.status_code == 401
    assert logged_in.status_code == 200
    assert logged_in.json()["email"] == EMAIL
    assert restored.status_code == 200


def test_duplicate_registration_is_rejected_without_extra_workspace(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()
    request = {"email": EMAIL, "password": PASSWORD}

    first = client.post("/api/v1/auth/register", json=request)
    duplicate = client.post("/api/v1/auth/register", json=request)

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "该邮箱已注册。"
    assert len(db_session.scalars(select(User)).all()) == 1
    assert len(db_session.scalars(select(Workspace)).all()) == 1
    assert len(db_session.scalars(select(Membership)).all()) == 1


def test_separate_users_receive_separate_workspaces(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()
    first = client.post(
        "/api/v1/auth/register",
        json={"email": "first@example.com", "password": PASSWORD},
    )
    client.post("/api/v1/auth/logout")
    second = client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": PASSWORD},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["user_id"] != second.json()["user_id"]
    assert first.json()["workspace_id"] != second.json()["workspace_id"]
    assert len(db_session.scalars(select(User)).all()) == 2
    assert len(db_session.scalars(select(Workspace)).all()) == 2


def test_registration_can_be_disabled_without_disabling_login(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: user_auth_settings(
        allow_public_registration=False
    )

    response = client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "当前环境未开放用户注册。"


def test_password_change_rotates_session_and_revokes_old_password(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
    )
    old_token = registered.cookies.get("socialpilot_session")
    assert old_token is not None

    wrong = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong-password", "new_password": "new-password-123"},
    )
    unchanged = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
    )
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "new-password-123"},
    )
    new_token = changed.cookies.get("socialpilot_session")

    assert wrong.status_code == 401
    assert unchanged.status_code == 422
    assert changed.status_code == 200
    assert changed.json()["authenticated"] is True
    assert new_token is not None and new_token != old_token
    sessions = db_session.scalars(select(AuthSession).order_by(AuthSession.id)).all()
    assert len(sessions) == 2
    assert sessions[0].revoked_at is not None
    assert sessions[1].revoked_at is None

    client.post("/api/v1/auth/logout")
    old_password = client.post(
        "/api/v1/auth/login",
        json={"username": EMAIL, "password": PASSWORD},
    )
    new_password = client.post(
        "/api/v1/auth/login",
        json={"username": EMAIL, "password": "new-password-123"},
    )
    assert old_password.status_code == 401
    assert new_password.status_code == 200


def test_logout_other_devices_keeps_current_session_active(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"email": EMAIL, "password": PASSWORD},
        ).status_code
        == 201
    )
    second_login = client.post(
        "/api/v1/auth/login",
        json={"username": EMAIL, "password": PASSWORD},
    )
    current_token = second_login.cookies.get("socialpilot_session")
    assert current_token is not None

    revoked = client.post("/api/v1/auth/sessions/revoke-others")
    current = client.get("/api/v1/auth/session")

    assert revoked.status_code == 200
    assert revoked.json() == {"revoked_sessions": 1}
    assert current.status_code == 200
    assert current.json()["authenticated"] is True
    sessions = db_session.scalars(select(AuthSession).order_by(AuthSession.id)).all()
    assert len(sessions) == 2
    assert sessions[0].revoked_at is not None
    assert sessions[1].revoked_at is None


def test_login_failures_are_persistently_rate_limited_without_plain_email(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = lambda: user_auth_settings(
        user_auth_login_max_failures=3,
        user_auth_login_window_seconds=900,
        user_auth_login_lock_seconds=600,
    )
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"email": EMAIL, "password": PASSWORD},
        ).status_code
        == 201
    )
    client.post("/api/v1/auth/logout")

    responses = [
        client.post(
            "/api/v1/auth/login",
            json={"username": EMAIL, "password": "wrong-password"},
        )
        for _ in range(3)
    ]
    blocked_correct_password = client.post(
        "/api/v1/auth/login",
        json={"username": EMAIL, "password": PASSWORD},
    )

    assert [response.status_code for response in responses] == [401, 401, 429]
    assert int(responses[-1].headers["retry-after"]) > 0
    assert blocked_correct_password.status_code == 429
    throttle = db_session.scalar(select(LoginThrottle))
    assert throttle is not None
    assert throttle.failure_count == 3
    assert throttle.locked_until is not None
    assert EMAIL not in throttle.scope_hash


def test_password_reset_is_private_one_time_and_revokes_existing_sessions(
    client: TestClient,
    db_session: Session,
) -> None:
    sender = FakeAccountEmailSender()
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()
    app.dependency_overrides[get_account_email_sender] = lambda: sender
    assert client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
    ).status_code == 201

    known = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": EMAIL},
    )
    unknown = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "unknown@example.com"},
    )

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(sender.password_resets) == 1
    recipient, token = sender.password_resets[0]
    assert recipient == EMAIL
    assert token not in known.text
    stored = db_session.scalar(select(AccountActionToken))
    assert stored is not None
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored.token_hash

    reset = client.post(
        "/api/v1/auth/password-reset/complete",
        json={"token": token, "new_password": "replacement-password-123"},
    )
    repeated = client.post(
        "/api/v1/auth/password-reset/complete",
        json={"token": token, "new_password": "another-password-123"},
    )
    session = client.get("/api/v1/auth/session")
    old_login = client.post(
        "/api/v1/auth/login",
        json={"username": EMAIL, "password": PASSWORD},
    )
    new_login = client.post(
        "/api/v1/auth/login",
        json={"username": EMAIL, "password": "replacement-password-123"},
    )

    assert reset.status_code == 200
    assert repeated.status_code == 400
    assert session.json()["authenticated"] is False
    assert old_login.status_code == 401
    assert new_login.status_code == 200
    assert stored.consumed_at is not None
    sessions = db_session.scalars(select(AuthSession).order_by(AuthSession.id)).all()
    assert sessions[0].revoked_at is not None


def test_email_verification_marks_user_and_token_is_one_time(
    client: TestClient,
    db_session: Session,
) -> None:
    sender = FakeAccountEmailSender()
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()
    app.dependency_overrides[get_account_email_sender] = lambda: sender
    client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
    )

    requested = client.post("/api/v1/auth/email-verification/request")
    assert requested.status_code == 202
    assert len(sender.email_verifications) == 1
    recipient, token = sender.email_verifications[0]
    assert recipient == EMAIL
    assert token not in requested.text

    verified = client.post(
        "/api/v1/auth/email-verification/complete",
        json={"token": token},
    )
    repeated = client.post(
        "/api/v1/auth/email-verification/complete",
        json={"token": token},
    )
    session = client.get("/api/v1/auth/session")
    user = db_session.scalar(select(User).where(User.email == EMAIL))

    assert verified.status_code == 200
    assert repeated.status_code == 400
    assert session.json()["email_verified"] is True
    assert user is not None and user.email_verified_at is not None


def test_unconfigured_email_delivery_is_safe_and_explicit_for_signed_in_user(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()
    client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
    )

    reset = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": EMAIL},
    )
    verification = client.post("/api/v1/auth/email-verification/request")

    assert reset.status_code == 202
    assert "令牌" not in reset.text
    assert verification.status_code == 503
    assert verification.json()["detail"] == "系统邮件服务尚未配置，请联系管理员。"
    assert db_session.scalar(select(AccountActionToken)) is None
