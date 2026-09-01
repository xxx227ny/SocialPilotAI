from sqlalchemy.orm import Session

from app.api.v1.routes.social import _oauth_cookie_secure
from app.core.config import Settings
from app.services.demo_auth_service import hash_password
from app.services.pinterest_account_service import PinterestAccountService
from app.services.tiktok_account_service import TikTokAccountService


def test_product_auth_uses_secure_oauth_browser_cookie() -> None:
    settings = Settings(
        _env_file=None,
        enable_user_auth=True,
        user_auth_cookie_secure=True,
    )

    assert _oauth_cookie_secure(settings) is True


def test_demo_cookie_policy_remains_backward_compatible() -> None:
    secure_demo = Settings(
        _env_file=None,
        enable_demo_auth=True,
        demo_auth_username="demo-user",
        demo_auth_password_hash=hash_password(
            "strong-demo-password", salt=b"oauth-test-salt-123"
        ),
        demo_auth_session_secret="oauth-test-session-secret-123456",
        demo_auth_cookie_secure=True,
    )
    disabled_auth = Settings(_env_file=None)

    assert _oauth_cookie_secure(secure_demo) is True
    assert _oauth_cookie_secure(disabled_auth) is False


def test_tiktok_and_pinterest_allow_clean_https_product_redirects(
    db_session: Session,
) -> None:
    settings = Settings(
        _env_file=None,
        social_frontend_base_url="https://app.socialpilot.example/",
    )

    tiktok = TikTokAccountService(db_session, settings, None)._frontend_redirect(
        "/products", "connected"
    )
    pinterest = PinterestAccountService(db_session, settings, None)._frontend_redirect(
        "/products", "connected"
    )

    assert tiktok == ("https://app.socialpilot.example/products?tiktok_oauth=connected")
    assert pinterest == (
        "https://app.socialpilot.example/products?pinterest_oauth=connected"
    )
