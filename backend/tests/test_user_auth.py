from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import AuthSession, Membership, User, Workspace

EMAIL = "owner@example.com"
PASSWORD = "strong-user-password"


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
    assert client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
    ).status_code == 201

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
