from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_instagram_provider
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.main import app
from app.models import OAuthSession, Product, SocialAccount
from app.providers.instagram_provider import (
    INSTAGRAM_SCOPES,
    InstagramLongToken,
    InstagramProfessionalProfile,
    InstagramProvider,
    InstagramProviderError,
    InstagramShortToken,
)
from app.services.social_security import TokenCipher, digest_oauth_state
from app.services.social_service import SocialAccountService

SHORT_TOKEN = "fake-instagram-short-token"
LONG_TOKEN = "fake-instagram-long-token"


class FakeInstagramProvider:
    def __init__(self, *, account_type: str = "BUSINESS", scopes=INSTAGRAM_SCOPES):
        self.account_type = account_type
        self.scopes = tuple(scopes)
        self.authorization_calls = 0
        self.exchange_calls = 0
        self.long_token_calls = 0
        self.profile_calls = 0

    def authorization_url(self, *, state: str) -> str:
        self.authorization_calls += 1
        return "https://www.instagram.com/oauth/authorize?" + (
            f"state={state}&scope={','.join(INSTAGRAM_SCOPES)}"
        )

    async def exchange_code(self, *, code: str) -> InstagramShortToken:
        self.exchange_calls += 1
        assert code == "fake-instagram-code"
        return InstagramShortToken(SHORT_TOKEN, "178414000000001", self.scopes)

    async def exchange_long_lived_token(self, short_token: str) -> InstagramLongToken:
        self.long_token_calls += 1
        assert short_token == SHORT_TOKEN
        return InstagramLongToken(LONG_TOKEN, datetime.now(UTC) + timedelta(days=60))

    async def get_professional_profile(
        self, *, user_id: str, access_token: str
    ) -> InstagramProfessionalProfile:
        self.profile_calls += 1
        assert user_id == "178414000000001"
        assert access_token == LONG_TOKEN
        return InstagramProfessionalProfile(
            user_id, "fake_professional", self.account_type
        )


def settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_instagram_account_binding=True,
        instagram_app_id="fake-instagram-app-id",
        instagram_app_secret="fake-instagram-app-secret",
        instagram_oauth_redirect_uri=(
            "http://127.0.0.1:8000/api/v1/social-accounts/instagram/callback"
        ),
        instagram_graph_api_version="v23.0",
        social_token_encryption_key=Fernet.generate_key().decode("ascii"),
    )


def product(db: Session, name: str = "Instagram Product") -> Product:
    item = Product(name=name, selling_points=["safe"], target_markets=["US"])
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def configure(
    provider: FakeInstagramProvider, configured: Settings | None = None
) -> Settings:
    configured = configured or settings()
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_instagram_provider] = lambda: provider
    return configured


def connect(client: TestClient, product_id: int) -> tuple[str, str]:
    response = client.post(
        "/api/v1/social-accounts/instagram/connect", json={"product_id": product_id}
    )
    assert response.status_code == 200
    url = response.json()["authorization_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    return state, response.headers.get("set-cookie", "")


def callback(client: TestClient, state: str, **params: str):
    return client.get(
        "/api/v1/social-accounts/instagram/callback",
        params={"state": state, **params},
        follow_redirects=False,
    )


def test_gate_blocks_before_provider_resolution(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    calls = 0

    def forbidden():
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not resolve")

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_instagram_provider] = forbidden
    response = client.post(
        "/api/v1/social-accounts/instagram/connect", json={"product_id": item.id}
    )
    assert response.status_code == 503
    assert calls == 0


def test_connect_uses_new_scopes_digest_and_shared_cookie_path(
    client: TestClient, db_session: Session
) -> None:
    provider = FakeInstagramProvider()
    configure(provider)
    item = product(db_session)
    state, cookie = connect(client, item.id)
    stored = db_session.scalar(select(OAuthSession))
    assert stored is not None
    assert stored.platform == "instagram"
    assert stored.state_digest == hashlib.sha256(state.encode()).hexdigest()
    assert state not in stored.state_digest
    assert "Path=/api/v1/social-accounts" in cookie
    assert set(INSTAGRAM_SCOPES) == {
        "instagram_business_basic",
        "instagram_business_content_publish",
    }
    assert all(not scope.startswith("business_") for scope in INSTAGRAM_SCOPES)
    assert provider.authorization_calls == 1


def test_real_provider_contract_uses_fixed_version_exact_scopes_and_bearer() -> None:
    configured = settings()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "api.instagram.com":
            form = parse_qs(request.content.decode("utf-8"))
            assert request.method == "POST"
            assert form == {
                "client_id": ["fake-instagram-app-id"],
                "client_secret": ["fake-instagram-app-secret"],
                "grant_type": ["authorization_code"],
                "redirect_uri": [
                    "http://127.0.0.1:8000/api/v1/social-accounts/instagram/callback"
                ],
                "code": ["fake-contract-code"],
            }
            return httpx.Response(
                200,
                json={
                    "access_token": SHORT_TOKEN,
                    "user_id": "178414000000001",
                    "permissions": list(INSTAGRAM_SCOPES),
                },
            )
        if request.url.path == "/access_token":
            query = dict(request.url.params)
            assert request.method == "GET"
            assert query == {
                "grant_type": "ig_exchange_token",
                "client_secret": "fake-instagram-app-secret",
                "access_token": SHORT_TOKEN,
            }
            return httpx.Response(
                200, json={"access_token": LONG_TOKEN, "expires_in": 5_184_000}
            )
        assert request.method == "GET"
        assert request.url.path == "/v23.0/178414000000001"
        assert dict(request.url.params) == {"fields": "id,username,account_type"}
        assert request.headers["authorization"] == f"Bearer {LONG_TOKEN}"
        assert LONG_TOKEN not in str(request.url)
        return httpx.Response(
            200,
            json={
                "id": "178414000000001",
                "username": "fake_professional",
                "account_type": "BUSINESS",
            },
        )

    provider = InstagramProvider(configured, transport=httpx.MockTransport(handler))
    authorization_url = provider.authorization_url(state="s" * 48)
    query = parse_qs(urlparse(authorization_url).query)
    assert query["scope"] == [",".join(INSTAGRAM_SCOPES)]
    assert query["scope"][0].split(",") == list(INSTAGRAM_SCOPES)
    assert "business_basic" not in query["scope"][0].split(",")
    assert "business_content_publish" not in query["scope"][0].split(",")
    assert configured.instagram_graph_api_version == "v23.0"

    async def exercise_contract() -> None:
        short = await provider.exchange_code(code="fake-contract-code")
        long_token = await provider.exchange_long_lived_token(short.access_token)
        profile = await provider.get_professional_profile(
            user_id=short.user_id, access_token=long_token.access_token
        )
        assert profile.account_id == short.user_id

    asyncio.run(exercise_contract())
    assert len(requests) == 3


@pytest.mark.parametrize("failure", ["network", "http", "invalid_json"])
def test_real_provider_failures_drop_sensitive_request_context(failure: str) -> None:
    configured = settings()
    secret = configured.instagram_app_secret.get_secret_value()  # type: ignore[union-attr]

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "network":
            raise httpx.ConnectError(
                f"transport failed for {SHORT_TOKEN} and {secret}", request=request
            )
        if failure == "http":
            return httpx.Response(400, text=f"rejected {SHORT_TOKEN} {secret}")
        return httpx.Response(200, text=f"not-json {SHORT_TOKEN} {secret}")

    provider = InstagramProvider(configured, transport=httpx.MockTransport(handler))
    with pytest.raises(InstagramProviderError) as captured:
        asyncio.run(provider.exchange_long_lived_token(SHORT_TOKEN))

    error = captured.value
    serialized = " ".join(
        (str(error), repr(error), repr(error.__cause__), repr(error.__context__))
    )
    assert error.safe_error_code in {
        "instagram_provider_unavailable",
        "instagram_provider_rejected_request",
        "invalid_provider_response",
    }
    assert error.__cause__ is None
    assert error.__context__ is None
    assert SHORT_TOKEN not in serialized
    assert secret not in serialized


@pytest.mark.parametrize("account_type", ["BUSINESS", "CREATOR", "MEDIA_CREATOR"])
def test_professional_callback_encrypts_and_replays_without_duplicates(
    client: TestClient, db_session: Session, account_type: str
) -> None:
    provider = FakeInstagramProvider(account_type=account_type)
    configured = configure(provider)
    item = product(db_session)
    state, _ = connect(client, item.id)
    response = callback(client, state, code="fake-instagram-code")
    assert response.status_code == 303
    assert response.headers["location"].endswith("?instagram_oauth=connected")
    account = db_session.scalar(select(SocialAccount))
    assert account is not None
    assert account.platform == "instagram"
    assert account.provider_account_id == "178414000000001"
    assert account.display_name == "fake_professional"
    assert account.scopes == list(INSTAGRAM_SCOPES)
    assert account.access_token_ciphertext not in {SHORT_TOKEN, LONG_TOKEN}
    assert (
        TokenCipher(configured).decrypt(account.access_token_ciphertext or "")
        == LONG_TOKEN
    )
    assert account.encryption_key_id == configured.social_token_encryption_key_id
    assert account.refresh_token_ciphertext is None

    state2, _ = connect(client, item.id)
    assert callback(client, state2, code="fake-instagram-code").status_code == 303
    assert db_session.scalar(select(func.count(SocialAccount.id))) == 1
    assert (
        provider.exchange_calls,
        provider.long_token_calls,
        provider.profile_calls,
    ) == (2, 2, 2)


@pytest.mark.parametrize(
    "account_type,scopes",
    [
        ("PERSONAL", INSTAGRAM_SCOPES),
        ("CONSUMER", INSTAGRAM_SCOPES),
        ("BUSINESS", (INSTAGRAM_SCOPES[0],)),
        ("CREATOR", (*INSTAGRAM_SCOPES, "unexpected_scope")),
    ],
)
def test_invalid_professional_identity_or_scope_is_safe_failure(
    client: TestClient, db_session: Session, account_type: str, scopes: tuple[str, ...]
) -> None:
    provider = FakeInstagramProvider(account_type=account_type, scopes=scopes)
    configure(provider)
    item = product(db_session)
    state, _ = connect(client, item.id)
    response = callback(client, state, code="fake-instagram-code")
    assert response.status_code == 303
    assert response.headers["location"].endswith("?instagram_oauth=failed")
    assert db_session.scalar(select(func.count(SocialAccount.id))) == 0
    serialized = response.headers["location"] + response.text
    assert SHORT_TOKEN not in serialized and LONG_TOKEN not in serialized


def test_denied_one_time_browser_expiry_and_cross_platform_isolation(
    client: TestClient, db_session: Session
) -> None:
    provider = FakeInstagramProvider()
    configure(provider)
    item = product(db_session)
    state, _ = connect(client, item.id)
    denied = callback(client, state, error="access_denied")
    assert denied.headers["location"].endswith("?instagram_oauth=denied")
    assert callback(client, state, code="fake-instagram-code").status_code == 409
    assert provider.exchange_calls == 0

    state2, _ = connect(client, item.id)
    client.cookies.set("social_oauth_browser", "wrong-browser")
    assert callback(client, state2, code="fake-instagram-code").status_code == 400
    session = db_session.scalar(
        select(OAuthSession).where(
            OAuthSession.state_digest == digest_oauth_state(state2)
        )
    )
    assert session is not None and session.consumed_at is None

    cross_state = "x" * 48
    db_session.add(
        OAuthSession(
            product_id=item.id,
            platform="youtube",
            state_digest=digest_oauth_state(cross_state),
            browser_session_digest="irrelevant",
            pkce_verifier_ciphertext="fake",
            redirect_path="/products",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    db_session.commit()
    assert callback(client, cross_state, code="fake-instagram-code").status_code == 400

    instagram_state, _ = connect(client, item.id)
    instagram_session = db_session.scalar(
        select(OAuthSession).where(
            OAuthSession.state_digest == digest_oauth_state(instagram_state)
        )
    )
    assert instagram_session is not None
    with pytest.raises(AppError, match="OAuth state is invalid"):
        asyncio.run(
            SocialAccountService(
                db_session,
                settings().model_copy(update={"enable_social_account_binding": True}),
                None,
            ).callback(
                state=instagram_state,
                browser_session_digest=instagram_session.browser_session_digest,
                code="fake-youtube-code",
                error=None,
            )
        )

    expired_state = "e" * 48
    browser = "expiry-browser"
    client.cookies.set("social_oauth_browser", browser)
    db_session.add(
        OAuthSession(
            product_id=item.id,
            platform="instagram",
            state_digest=digest_oauth_state(expired_state),
            browser_session_digest=digest_oauth_state(browser),
            pkce_verifier_ciphertext="fake",
            redirect_path="/products",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    db_session.commit()
    assert (
        callback(client, expired_state, code="fake-instagram-code").status_code == 410
    )


def test_cross_product_isolation_and_local_disconnect_provider_free(
    client: TestClient, db_session: Session
) -> None:
    provider = FakeInstagramProvider()
    configure(provider)
    first = product(db_session, "First")
    second = product(db_session, "Second")
    for item in (first, second):
        state, _ = connect(client, item.id)
        assert callback(client, state, code="fake-instagram-code").status_code == 303
    accounts = list(
        db_session.scalars(select(SocialAccount).order_by(SocialAccount.id))
    )
    assert len(accounts) == 2 and accounts[0].product_id != accounts[1].product_id
    before = (
        provider.exchange_calls,
        provider.long_token_calls,
        provider.profile_calls,
    )
    denied = client.post(
        f"/api/v1/social-accounts/instagram/{accounts[0].id}/disconnect",
        json={"product_id": second.id, "confirm_disconnect": True},
    )
    assert denied.status_code == 404
    response = client.post(
        f"/api/v1/social-accounts/instagram/{accounts[0].id}/disconnect",
        json={"product_id": first.id, "confirm_disconnect": True},
    )
    assert response.status_code == 200
    assert response.json()["local_only"] is True
    assert response.json()["meta_authorization_revoked"] is False
    db_session.refresh(accounts[0])
    assert accounts[0].connection_status == "DISCONNECTED"
    assert accounts[0].access_token_ciphertext is None
    assert accounts[0].refresh_token_ciphertext is None
    assert (
        provider.exchange_calls,
        provider.long_token_calls,
        provider.profile_calls,
    ) == before
    serialized = json.dumps(response.json())
    assert SHORT_TOKEN not in serialized and LONG_TOKEN not in serialized
