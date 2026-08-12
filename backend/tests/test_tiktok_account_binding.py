from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, parse_qsl, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_tiktok_provider
from app.core.config import Settings, get_settings
from app.main import app
from app.models import OAuthSession, Product, SocialAccount
from app.providers.tiktok_provider import (
    TIKTOK_SCOPES,
    TikTokProvider,
    TikTokProviderError,
    TikTokToken,
    TikTokUser,
)
from app.services.social_security import TokenCipher, digest_oauth_state

ACCESS_TOKEN = "fake-tiktok-access-token"
REFRESH_TOKEN = "fake-tiktok-refresh-token"
CLIENT_SECRET = "fake-tiktok-client-secret"
CODE = "fake-tiktok-code"
OPEN_ID = "fake-tiktok-open-id"


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "enable_tiktok_account_binding": True,
        "tiktok_client_key": "fake-tiktok-client-key",
        "tiktok_client_secret": CLIENT_SECRET,
        "tiktok_oauth_redirect_uri": (
            "https://app.example/api/v1/social-accounts/tiktok/callback"
        ),
        "social_token_encryption_key": Fernet.generate_key().decode("ascii"),
    }
    values.update(overrides)
    return Settings(**values)


def product(db: Session, name: str = "TikTok Product") -> Product:
    item = Product(name=name, selling_points=["safe"], target_markets=["US"])
    db.add(item)
    db.commit()
    return item


class FakeTikTokProvider:
    def __init__(self, *, scopes=TIKTOK_SCOPES, profile_open_id: str = OPEN_ID) -> None:
        self.scopes = tuple(scopes)
        self.profile_open_id = profile_open_id
        self.authorization_calls = 0
        self.exchange_calls = 0
        self.user_calls = 0

    def authorization_url(self, *, state: str) -> str:
        self.authorization_calls += 1
        return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode_for_test(
            {"state": state, "scope": ",".join(TIKTOK_SCOPES)}
        )

    async def exchange_code(self, *, code: str) -> TikTokToken:
        self.exchange_calls += 1
        assert code == CODE
        now = datetime.now(UTC)
        return TikTokToken(
            OPEN_ID,
            self.scopes,
            ACCESS_TOKEN,
            now + timedelta(hours=1),
            REFRESH_TOKEN,
            now + timedelta(days=30),
        )

    async def get_user(self, *, access_token: str) -> TikTokUser:
        self.user_calls += 1
        assert access_token == ACCESS_TOKEN
        return TikTokUser(self.profile_open_id, "Safe Creator")


def urlencode_for_test(values: dict[str, str]) -> str:
    return "&".join(f"{key}={value}" for key, value in values.items())


def configure(
    provider: FakeTikTokProvider, configured: Settings | None = None
) -> Settings:
    configured = configured or settings()
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_tiktok_provider] = lambda: provider
    return configured


def connect(client: TestClient, product_id: int) -> str:
    response = client.post(
        "/api/v1/social-accounts/tiktok/connect", json={"product_id": product_id}
    )
    assert response.status_code == 200
    return parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]


def callback(client: TestClient, state: str, **params: str):
    return client.get(
        "/api/v1/social-accounts/tiktok/callback",
        params={"state": state, **params},
        follow_redirects=False,
    )


def test_gate_fails_closed_before_provider_or_database_write(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    calls = 0

    def forbidden():
        nonlocal calls
        calls += 1
        raise AssertionError("Provider must not resolve")

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_tiktok_provider] = forbidden
    response = client.post(
        "/api/v1/social-accounts/tiktok/connect", json={"product_id": item.id}
    )
    assert response.status_code == 503
    assert calls == 0
    assert db_session.scalar(select(func.count(OAuthSession.id))) == 0
    assert db_session.scalar(select(func.count(SocialAccount.id))) == 0


def test_authorization_and_mocktransport_http_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/oauth/token/":
            form = dict(parse_qsl(request.content.decode()))
            assert form == {
                "client_key": "fake-tiktok-client-key",
                "client_secret": CLIENT_SECRET,
                "code": CODE,
                "grant_type": "authorization_code",
                "redirect_uri": "https://app.example/api/v1/social-accounts/tiktok/callback",
            }
            assert request.headers["content-type"].startswith(
                "application/x-www-form-urlencoded"
            )
            return httpx.Response(
                200,
                json={
                    "open_id": OPEN_ID,
                    "scope": ",".join(TIKTOK_SCOPES),
                    "access_token": ACCESS_TOKEN,
                    "expires_in": 3600,
                    "refresh_token": REFRESH_TOKEN,
                    "refresh_expires_in": 86400,
                    "token_type": "Bearer",
                },
            )
        assert request.url.path == "/v2/user/info/"
        assert dict(request.url.params) == {"fields": "open_id,display_name"}
        assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
        assert ACCESS_TOKEN not in str(request.url)
        return httpx.Response(
            200,
            json={
                "data": {"user": {"open_id": OPEN_ID, "display_name": "Creator"}},
                "error": {"code": "ok", "message": "", "log_id": "fake"},
            },
        )

    provider = TikTokProvider(settings(), transport=httpx.MockTransport(handler))
    parsed = urlparse(provider.authorization_url(state="safe-state"))
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://www.tiktok.com/v2/auth/authorize/"
    )
    assert parse_qs(parsed.query) == {
        "client_key": ["fake-tiktok-client-key"],
        "response_type": ["code"],
        "scope": [",".join(TIKTOK_SCOPES)],
        "redirect_uri": ["https://app.example/api/v1/social-accounts/tiktok/callback"],
        "state": ["safe-state"],
        "disable_auto_auth": ["1"],
    }
    assert "code_challenge" not in parsed.query and "code_verifier" not in parsed.query
    token = asyncio.run(provider.exchange_code(code=CODE))
    user = asyncio.run(provider.get_user(access_token=token.access_token))
    assert user.open_id == token.open_id == OPEN_ID
    assert len(requests) == 2


@pytest.mark.parametrize(
    "mutation",
    [
        {"token_type": "mac"},
        {"expires_in": 0},
        {"expires_in": 60 * 60 * 24 * 367},
        {"refresh_expires_in": -1},
        {"refresh_token": ""},
        {"open_id": None},
    ],
)
def test_token_response_is_strict(mutation: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "open_id": OPEN_ID,
        "scope": ",".join(TIKTOK_SCOPES),
        "access_token": ACCESS_TOKEN,
        "expires_in": 3600,
        "refresh_token": REFRESH_TOKEN,
        "refresh_expires_in": 86400,
        "token_type": "Bearer",
    }
    payload.update(mutation)
    provider = TikTokProvider(
        settings(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    with pytest.raises(TikTokProviderError):
        asyncio.run(provider.exchange_code(code=CODE))


@pytest.mark.parametrize("kind", ["network", "http", "json", "body"])
def test_provider_errors_are_secret_and_body_safe(kind: str) -> None:
    raw_body = "provider-raw-sensitive-body"

    def handler(request: httpx.Request) -> httpx.Response:
        if kind == "network":
            raise httpx.ConnectError(f"{CLIENT_SECRET} {CODE}", request=request)
        if kind == "http":
            return httpx.Response(400, text=f"{raw_body} {REFRESH_TOKEN}")
        if kind == "json":
            return httpx.Response(200, text=f"{raw_body} {ACCESS_TOKEN}")
        return httpx.Response(200, json={"access_token": ACCESS_TOKEN})

    provider = TikTokProvider(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(TikTokProviderError) as caught:
        asyncio.run(provider.exchange_code(code=CODE))
    values = " ".join(
        [
            str(caught.value),
            repr(caught.value),
            str(caught.value.__cause__),
            str(caught.value.__context__),
        ]
    )
    for secret in (CLIENT_SECRET, CODE, ACCESS_TOKEN, REFRESH_TOKEN, raw_body):
        assert secret not in values
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_callback_encrypts_tokens_rebinds_and_disconnects_locally(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    provider = FakeTikTokProvider(scopes=("video.publish", "user.info.basic"))
    configured = configure(provider)
    state = connect(client, item.id)
    response = callback(client, state, code=CODE)
    assert response.status_code == 303
    assert response.headers["location"].endswith("?tiktok_oauth=connected")
    account = db_session.scalar(select(SocialAccount))
    assert account is not None
    assert account.platform == "tiktok"
    assert account.provider_account_id == OPEN_ID
    assert account.scopes == list(TIKTOK_SCOPES)
    cipher = TokenCipher(configured)
    assert cipher.decrypt(account.access_token_ciphertext) == ACCESS_TOKEN
    assert cipher.decrypt(account.refresh_token_ciphertext) == REFRESH_TOKEN
    assert account.token_expires_at and account.refresh_token_expires_at
    assert ACCESS_TOKEN not in account.access_token_ciphertext
    assert REFRESH_TOKEN not in account.refresh_token_ciphertext

    state2 = connect(client, item.id)
    assert callback(client, state2, code=CODE).status_code == 303
    assert db_session.scalar(select(func.count(SocialAccount.id))) == 1

    disconnected = client.post(
        f"/api/v1/social-accounts/tiktok/{account.id}/disconnect",
        json={"product_id": item.id, "confirm_disconnect": True},
    )
    assert disconnected.status_code == 200
    db_session.refresh(account)
    assert account.connection_status == "DISCONNECTED"
    assert account.access_token_ciphertext is None
    assert account.refresh_token_ciphertext is None
    assert account.token_expires_at is None
    assert account.refresh_token_expires_at is None
    assert provider.exchange_calls == 2 and provider.user_calls == 2


def test_cross_product_isolation_and_exact_reads(
    client: TestClient, db_session: Session
) -> None:
    first, second = product(db_session, "First"), product(db_session, "Second")
    provider = FakeTikTokProvider()
    configure(provider)
    for item in (first, second):
        assert callback(client, connect(client, item.id), code=CODE).status_code == 303
    accounts = list(db_session.scalars(select(SocialAccount)).all())
    assert len(accounts) == 2
    assert {item.product_id for item in accounts} == {first.id, second.id}
    response = client.get(
        f"/api/v1/social-accounts/{accounts[0].id}",
        params={"product_id": second.id},
    )
    assert response.status_code == 404
    response = client.post(
        f"/api/v1/social-accounts/tiktok/{accounts[0].id}/disconnect",
        json={"product_id": second.id, "confirm_disconnect": True},
    )
    assert response.status_code == 404


def test_state_cookie_expiry_replay_denial_and_platform_isolation(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    provider = FakeTikTokProvider()
    configure(provider)
    state = connect(client, item.id)
    client.cookies.clear()
    assert callback(client, state, code=CODE).status_code == 400

    state = connect(client, item.id)
    denied = callback(client, state, error="access_denied")
    assert denied.status_code == 303
    assert denied.headers["location"].endswith("?tiktok_oauth=denied")
    assert callback(client, state, code=CODE).status_code == 409

    state = connect(client, item.id)
    oauth = db_session.scalar(
        select(OAuthSession).where(
            OAuthSession.state_digest == digest_oauth_state(state)
        )
    )
    assert oauth is not None
    oauth.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert callback(client, state, code=CODE).status_code == 410

    for platform in ("youtube", "instagram"):
        cross = "cross-platform-state-value-123456789"
        db_session.add(
            OAuthSession(
                product_id=item.id,
                platform=platform,
                state_digest=digest_oauth_state(cross + platform),
                browser_session_digest="safe",
                pkce_verifier_ciphertext="safe",
                redirect_path="/products",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        db_session.commit()
        assert callback(client, cross + platform, code=CODE).status_code == 400
    assert provider.exchange_calls == provider.user_calls == 0


@pytest.mark.parametrize(
    "scopes",
    [(), ("user.info.basic",), ("video.publish",), (*TIKTOK_SCOPES, "video.list")],
)
def test_scope_mismatch_never_reads_user_or_saves_account(
    client: TestClient, db_session: Session, scopes: tuple[str, ...]
) -> None:
    item = product(db_session)
    provider = FakeTikTokProvider(scopes=scopes)
    configure(provider)
    response = callback(client, connect(client, item.id), code=CODE)
    assert response.headers["location"].endswith("?tiktok_oauth=failed")
    assert provider.exchange_calls == 1
    assert provider.user_calls == 0
    assert db_session.scalar(select(func.count(SocialAccount.id))) == 0


def test_user_open_id_mismatch_fails_without_account(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    provider = FakeTikTokProvider(profile_open_id="other-open-id")
    configure(provider)
    response = callback(client, connect(client, item.id), code=CODE)
    assert response.headers["location"].endswith("?tiktok_oauth=failed")
    assert provider.exchange_calls == provider.user_calls == 1
    assert db_session.scalar(select(func.count(SocialAccount.id))) == 0


def test_redirect_configuration_requires_absolute_clean_https() -> None:
    for uri in (
        "http://app.example/callback",
        "https://user@app.example/callback",
        "https://app.example/callback?code=x",
        "https://app.example/callback#fragment",
        "/relative/callback",
    ):
        with pytest.raises(TikTokProviderError):
            TikTokProvider(settings(tiktok_oauth_redirect_uri=uri))


def test_browser_safe_response_never_contains_sensitive_identity(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    configure(FakeTikTokProvider())
    response = callback(client, connect(client, item.id), code=CODE)
    location = response.headers["location"]
    serialized = json.dumps(response.json()) if response.is_success else location
    for sensitive in (CODE, OPEN_ID, ACCESS_TOKEN, REFRESH_TOKEN, "scope"):
        assert sensitive not in location
        assert sensitive not in serialized
