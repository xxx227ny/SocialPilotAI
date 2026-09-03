from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import AccountActionToken, User
from app.models.product import utc_now
from app.services.account_action_service import cleanup_account_action_tokens
from app.services.account_email_service import get_account_email_sender

EMAIL = "verification-policy@example.com"
PASSWORD = "strong-user-password"


class CapturingEmailSender:
    configured = True

    def __init__(self) -> None:
        self.verification_tokens: list[str] = []

    def send_password_reset(self, recipient: str, token: str) -> None:
        del recipient, token

    def send_email_verification(self, recipient: str, token: str) -> None:
        assert recipient == EMAIL
        self.verification_tokens.append(token)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "enable_user_auth": True,
        "allow_public_registration": True,
        "user_auth_session_ttl_seconds": 3600,
        "user_auth_cookie_secure": False,
        "account_email_request_cooldown_seconds": 60,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_verified_email_policy_blocks_workspace_but_keeps_account_actions(
    client: TestClient,
) -> None:
    sender = CapturingEmailSender()
    app.dependency_overrides[get_settings] = lambda: settings(
        account_public_web_origin="https://product.example",
        account_email_from="noreply@example.com",
        account_smtp_host="smtp.example.com",
        account_require_verified_email=True,
    )
    app.dependency_overrides[get_account_email_sender] = lambda: sender

    registered = client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
    )

    assert registered.status_code == 201
    assert registered.json()["email_verification_required"] is True
    assert 1 <= registered.json()["email_verification_retry_after_seconds"] <= 60
    assert len(sender.verification_tokens) == 1
    # Readiness remains visible so the account page can show SMTP state. Its
    # aggregate status can still be 503 when unrelated providers are absent.
    assert client.get("/api/v1/system/readiness").status_code in {200, 503}
    blocked = client.get("/api/v1/products")
    assert blocked.status_code == 403
    assert "邮箱验证" in blocked.json()["detail"]

    repeated = client.post("/api/v1/auth/email-verification/request")
    assert repeated.status_code == 429
    assert 1 <= int(repeated.headers["retry-after"]) <= 60
    assert "秒后重试" in repeated.json()["detail"]

    verified = client.post(
        "/api/v1/auth/email-verification/complete",
        json={"token": sender.verification_tokens[0]},
    )
    session = client.get("/api/v1/auth/session")

    assert verified.status_code == 200
    assert session.json()["email_verified"] is True
    assert session.json()["email_verification_retry_after_seconds"] == 0
    assert client.get("/api/v1/products").status_code == 200


def test_verification_policy_never_locks_users_before_delivery_is_configured(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: settings(
        account_require_verified_email=True
    )

    registered = client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
    )

    assert registered.status_code == 201
    assert registered.json()["email_delivery_available"] is False
    assert registered.json()["email_verification_required"] is False
    assert client.get("/api/v1/products").status_code == 200


def test_account_token_cleanup_preserves_only_usable_or_recent_audit_rows(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = lambda: settings()
    client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
    )
    user = db_session.scalar(select(User).where(User.email == EMAIL))
    assert user is not None
    now = utc_now()
    tokens = (
        AccountActionToken(
            user_id=user.id,
            purpose="EMAIL_VERIFICATION",
            token_hash="a" * 64,
            expires_at=now - timedelta(seconds=1),
            created_at=now - timedelta(days=2),
        ),
        AccountActionToken(
            user_id=user.id,
            purpose="PASSWORD_RESET",
            token_hash="b" * 64,
            expires_at=now + timedelta(days=1),
            consumed_at=now - timedelta(days=8),
            created_at=now - timedelta(days=9),
        ),
        AccountActionToken(
            user_id=user.id,
            purpose="PASSWORD_RESET",
            token_hash="c" * 64,
            expires_at=now + timedelta(days=1),
            consumed_at=now - timedelta(hours=1),
            created_at=now - timedelta(hours=2),
        ),
        AccountActionToken(
            user_id=user.id,
            purpose="EMAIL_VERIFICATION",
            token_hash="d" * 64,
            expires_at=now + timedelta(days=1),
            created_at=now,
        ),
    )
    db_session.add_all(tokens)
    db_session.commit()

    removed = cleanup_account_action_tokens(
        db_session,
        retention_seconds=604_800,
        now=now,
    )
    db_session.commit()

    remaining = set(db_session.scalars(select(AccountActionToken.token_hash)).all())
    assert removed == 2
    assert remaining == {"c" * 64, "d" * 64}
