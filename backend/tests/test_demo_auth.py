from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app
from app.services.demo_auth_service import hash_password

USERNAME = "demo@socialpilot.local"
PASSWORD = "safe-demo-password"


def auth_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "enable_demo_auth": True,
        "demo_auth_username": USERNAME,
        "demo_auth_password_hash": hash_password(PASSWORD, salt=b"fixed-test-salt-123"),
        "demo_auth_session_secret": "fixed-test-session-secret-with-32-bytes",
        "demo_auth_session_ttl_seconds": 3600,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def configure_database_override(db_session: Session) -> None:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db


def test_disabled_auth_keeps_existing_api_compatible(db_session: Session) -> None:
    configure_database_override(db_session)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    client = TestClient(app)
    try:
        session = client.get("/api/v1/auth/session")
        products = client.get("/api/v1/products")
    finally:
        client.close()
        app.dependency_overrides.clear()

    assert session.status_code == 200
    assert session.json() == {
        "enabled": False,
        "authenticated": True,
        "username": None,
    }
    assert products.status_code == 200


def test_login_protects_workspace_and_logout_clears_session(
    db_session: Session,
) -> None:
    configure_database_override(db_session)
    app.dependency_overrides[get_settings] = lambda: auth_settings()
    client = TestClient(app)
    try:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False
        blocked = client.get("/api/v1/products")
        invalid = client.post(
            "/api/v1/auth/login",
            json={"username": USERNAME, "password": "wrong-password"},
        )
        logged_in = client.post(
            "/api/v1/auth/login",
            json={"username": USERNAME.upper(), "password": PASSWORD},
        )
        authenticated = client.get("/api/v1/products")
        session = client.get("/api/v1/auth/session")
        logged_out = client.post("/api/v1/auth/logout")
        blocked_again = client.get("/api/v1/products")
    finally:
        client.close()
        app.dependency_overrides.clear()

    assert blocked.status_code == 401
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "账号或密码不正确。"
    assert logged_in.status_code == 200
    cookie = logged_in.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert PASSWORD not in cookie
    assert authenticated.status_code == 200
    assert session.json() == {
        "enabled": True,
        "authenticated": True,
        "username": USERNAME,
    }
    assert logged_out.status_code == 200
    assert blocked_again.status_code == 401


def test_tampered_and_expired_sessions_are_rejected(db_session: Session) -> None:
    configure_database_override(db_session)
    settings = auth_settings(demo_auth_session_ttl_seconds=900)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    try:
        logged_in = client.post(
            "/api/v1/auth/login",
            json={"username": USERNAME, "password": PASSWORD},
        )
        cookie = logged_in.cookies.get("socialpilot_session")
        assert cookie is not None
        payload_text, signature_text = cookie.split(".", 1)
        changed_prefix = "A" if signature_text[0] != "A" else "B"
        client.cookies.delete("socialpilot_session")
        client.cookies.set(
            "socialpilot_session",
            f"{payload_text}.{changed_prefix}{signature_text[1:]}",
        )
        blocked = client.get("/api/v1/products")
    finally:
        client.close()
        app.dependency_overrides.clear()

    assert blocked.status_code == 401
