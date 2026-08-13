from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, parse_qsl, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_instagram_provider,
    get_pinterest_provider,
    get_tiktok_provider,
    get_youtube_provider,
)
from app.core.config import Settings, get_settings
from app.main import app
from app.models import OAuthSession, Product, SocialAccount
from app.providers.pinterest_provider import (
    PINTEREST_SCOPES,
    PinterestProvider,
    PinterestProviderError,
    PinterestToken,
    PinterestUser,
)
from app.services.social_security import TokenCipher

ACCESS = "fake-pinterest-access-token"
REFRESH = "fake-pinterest-refresh-token"
SECRET = "fake-pinterest-client-secret"
CODE = "fake-pinterest-code"


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "enable_pinterest_account_binding": True,
        "pinterest_client_id": "fake-pinterest-client-id",
        "pinterest_client_secret": SECRET,
        "pinterest_oauth_redirect_uri": "https://app.example/api/v1/social-accounts/pinterest/callback",
        "social_token_encryption_key": Fernet.generate_key().decode("ascii"),
    }
    values.update(overrides)
    return Settings(**values)


def product(db: Session, name: str = "Pinterest Product") -> Product:
    item = Product(name=name, selling_points=["safe"], target_markets=["US"])
    db.add(item)
    db.commit()
    return item


class FakeProvider:
    def __init__(self, scopes=PINTEREST_SCOPES) -> None:
        self.scopes = tuple(scopes)
        self.authorization_calls = 0
        self.exchange_calls = 0
        self.user_calls = 0

    def authorization_url(self, *, state: str) -> str:
        self.authorization_calls += 1
        return f"https://www.pinterest.com/oauth/?state={state}&scope={','.join(PINTEREST_SCOPES)}"

    async def exchange_code(self, *, code: str) -> PinterestToken:
        self.exchange_calls += 1
        assert code == CODE
        now = datetime.now(UTC)
        return PinterestToken(
            self.scopes,
            ACCESS,
            now + timedelta(hours=1),
            REFRESH,
            now + timedelta(days=30),
        )

    async def get_user_account(self, *, access_token: str) -> PinterestUser:
        self.user_calls += 1
        assert access_token == ACCESS
        return PinterestUser("fake-pinterest-id", "Safe Business", "BUSINESS")


def configure(provider: FakeProvider, configured: Settings | None = None) -> Settings:
    configured = configured or settings()
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_pinterest_provider] = lambda: provider
    return configured


def connect(client: TestClient, product_id: int) -> str:
    response = client.post(
        "/api/v1/social-accounts/pinterest/connect", json={"product_id": product_id}
    )
    assert response.status_code == 200
    return parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]


def callback(client: TestClient, state: str, **params: str):
    return client.get(
        "/api/v1/social-accounts/pinterest/callback",
        params={"state": state, **params},
        follow_redirects=False,
    )


def test_gate_fails_before_provider_and_database_write(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    calls = 0

    def forbidden():
        nonlocal calls
        calls += 1
        raise AssertionError

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_pinterest_provider] = forbidden
    response = client.post(
        "/api/v1/social-accounts/pinterest/connect", json={"product_id": item.id}
    )
    assert response.status_code == 503 and calls == 0
    assert db_session.scalar(select(func.count(OAuthSession.id))) == 0


def test_official_http_contract_uses_basic_and_bearer() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v5/oauth/token":
            expected = base64.b64encode(
                b"fake-pinterest-client-id:" + SECRET.encode()
            ).decode()
            assert request.headers["authorization"] == f"Basic {expected}"
            assert dict(parse_qsl(request.content.decode())) == {
                "grant_type": "authorization_code",
                "code": CODE,
                "redirect_uri": "https://app.example/api/v1/social-accounts/pinterest/callback",
            }
            return httpx.Response(
                200,
                json={
                    "access_token": ACCESS,
                    "refresh_token": REFRESH,
                    "token_type": "bearer",
                    "response_type": "authorization_code",
                    "expires_in": 3600,
                    "refresh_token_expires_in": 86400,
                    "scope": ",".join(PINTEREST_SCOPES),
                },
            )
        assert request.url.path == "/v5/user_account"
        assert request.headers["authorization"] == f"Bearer {ACCESS}"
        assert ACCESS not in str(request.url)
        return httpx.Response(
            200,
            json={
                "id": "123",
                "username": "safe",
                "business_name": "Safe Business",
                "account_type": "BUSINESS",
            },
        )

    provider = PinterestProvider(settings(), transport=httpx.MockTransport(handler))
    parsed = urlparse(provider.authorization_url(state="safe-state"))
    assert parsed.geturl().startswith("https://www.pinterest.com/oauth/")
    assert parse_qs(parsed.query)["scope"] == [",".join(PINTEREST_SCOPES)]
    token = asyncio.run(provider.exchange_code(code=CODE))
    user = asyncio.run(provider.get_user_account(access_token=token.access_token))
    assert user.account_id == "123" and len(requests) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "access_token": ACCESS,
            "refresh_token": REFRESH,
            "token_type": "mac",
            "expires_in": 3600,
            "refresh_token_expires_in": 3600,
            "scope": ",".join(PINTEREST_SCOPES),
        },
        {
            "access_token": ACCESS,
            "refresh_token": REFRESH,
            "token_type": "bearer",
            "expires_in": -1,
            "refresh_token_expires_in": 3600,
            "scope": ",".join(PINTEREST_SCOPES),
        },
    ],
)
def test_invalid_token_responses_are_safe(payload: dict[str, object]) -> None:
    provider = PinterestProvider(
        settings(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    with pytest.raises(PinterestProviderError) as caught:
        asyncio.run(provider.exchange_code(code=CODE))
    assert caught.value.safe_error_code.startswith("pinterest_")
    assert ACCESS not in repr(caught.value) and REFRESH not in repr(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"message": ACCESS}),
        httpx.Response(200, text=f"not-json-{REFRESH}"),
    ],
)
def test_http_and_json_errors_hide_provider_content(response: httpx.Response) -> None:
    provider = PinterestProvider(
        settings(), transport=httpx.MockTransport(lambda _: response)
    )
    with pytest.raises(PinterestProviderError) as caught:
        asyncio.run(provider.exchange_code(code=CODE))
    rendered = repr(caught.value)
    assert ACCESS not in rendered and REFRESH not in rendered and SECRET not in rendered


def test_network_error_has_no_sensitive_cause_or_context() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("safe failure", request=request)

    provider = PinterestProvider(settings(), transport=httpx.MockTransport(fail))
    with pytest.raises(PinterestProviderError) as caught:
        asyncio.run(provider.exchange_code(code=CODE))
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"id": "", "username": "safe", "account_type": "BUSINESS"},
        {"id": "123", "username": "", "account_type": "BUSINESS"},
        {"id": "123", "username": "safe", "account_type": "UNKNOWN"},
    ],
)
def test_invalid_user_identity_is_rejected(payload: dict[str, object]) -> None:
    provider = PinterestProvider(
        settings(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    with pytest.raises(PinterestProviderError):
        asyncio.run(provider.get_user_account(access_token=ACCESS))


def test_refresh_contract_uses_basic_auth_and_form_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Basic ")
        assert dict(parse_qsl(request.content.decode())) == {
            "grant_type": "refresh_token",
            "refresh_token": REFRESH,
        }
        return httpx.Response(
            200,
            json={
                "access_token": ACCESS,
                "refresh_token": REFRESH,
                "token_type": "bearer",
                "response_type": "refresh_token",
                "expires_in": 3600,
                "refresh_token_expires_in": 86400,
                "scope": ",".join(PINTEREST_SCOPES),
            },
        )

    token = asyncio.run(
        PinterestProvider(
            settings(), transport=httpx.MockTransport(handler)
        ).refresh_access_token(REFRESH)
    )
    assert token.access_token == ACCESS


def _token_payload(response_type: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "access_token": ACCESS,
        "refresh_token": REFRESH,
        "token_type": "bearer",
        "response_type": response_type,
        "expires_in": 3600,
        "refresh_token_expires_in": 86400,
        "scope": ",".join(PINTEREST_SCOPES),
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("method", "response_type"),
    [("exchange", "refresh_token"), ("refresh", "authorization_code")],
)
def test_token_response_type_cannot_cross_grants(
    method: str, response_type: str
) -> None:
    provider = PinterestProvider(
        settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=_token_payload(response_type))
        ),
    )
    with pytest.raises(PinterestProviderError):
        if method == "exchange":
            asyncio.run(provider.exchange_code(code=CODE))
        else:
            asyncio.run(provider.refresh_access_token(REFRESH))


def test_continuous_refresh_accepts_consistent_absolute_expiry() -> None:
    absolute = int((datetime.now(UTC) + timedelta(days=30)).timestamp())
    payload = _token_payload(
        "refresh_token",
        refresh_token_expires_in=30 * 86400,
        refresh_token_expires_at=absolute,
    )
    provider = PinterestProvider(
        settings(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    token = asyncio.run(provider.refresh_access_token(REFRESH))
    assert token.refresh_token == REFRESH
    assert abs(token.refresh_token_expires_at.timestamp() - absolute) < 1


@pytest.mark.parametrize(
    "expiry_fields",
    [
        {"refresh_token_expires_at": True, "refresh_token_expires_in": None},
        {"refresh_token_expires_at": "123", "refresh_token_expires_in": None},
        {"refresh_token_expires_at": 1, "refresh_token_expires_in": None},
        {
            "refresh_token_expires_at": int(
                (datetime.now(UTC) + timedelta(days=3661)).timestamp()
            ),
            "refresh_token_expires_in": None,
        },
        {
            "refresh_token_expires_at": int(
                (datetime.now(UTC) + timedelta(days=3)).timestamp()
            ),
            "refresh_token_expires_in": 86400,
        },
    ],
)
def test_refresh_absolute_expiry_rejects_unsafe_values(
    expiry_fields: dict[str, object],
) -> None:
    provider = PinterestProvider(
        settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=_token_payload("refresh_token", **expiry_fields),
            )
        ),
    )
    with pytest.raises(PinterestProviderError) as caught:
        asyncio.run(provider.refresh_access_token(REFRESH))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert ACCESS not in repr(caught.value) and REFRESH not in repr(caught.value)


def test_success_consumes_state_and_encrypts_tokens(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    provider = FakeProvider()
    configured = configure(provider)
    state = connect(client, item.id)
    response = callback(client, state, code=CODE)
    assert response.status_code == 303 and response.headers["location"].endswith(
        "?pinterest_oauth=connected"
    )
    account = db_session.scalar(select(SocialAccount))
    assert (
        account
        and account.platform == "pinterest"
        and account.connection_status == "CONNECTED"
    )
    assert account.access_token_ciphertext not in {ACCESS, None}
    assert account.refresh_token_ciphertext not in {REFRESH, None}
    cipher = TokenCipher(configured)
    assert cipher.decrypt(account.access_token_ciphertext) == ACCESS
    assert cipher.decrypt(account.refresh_token_ciphertext) == REFRESH
    assert db_session.scalar(select(OAuthSession)).consumed_at is not None
    assert provider.exchange_calls == provider.user_calls == 1
    assert ACCESS not in response.text and REFRESH not in response.text


@pytest.mark.parametrize("status", ["denied", "missing_code"])
def test_denied_and_missing_code_consume_state_without_provider(
    client: TestClient, db_session: Session, status: str
) -> None:
    item = product(db_session)
    provider = FakeProvider()
    configure(provider)
    state = connect(client, item.id)
    response = (
        callback(client, state, error="access_denied")
        if status == "denied"
        else callback(client, state)
    )
    assert response.status_code == 303
    assert db_session.scalar(select(OAuthSession)).consumed_at is not None
    assert provider.exchange_calls == provider.user_calls == 0


@pytest.mark.parametrize("foreign_platform", ["youtube", "instagram", "tiktok"])
def test_pinterest_callback_rejects_every_foreign_platform_state(
    client: TestClient, db_session: Session, foreign_platform: str
) -> None:
    item = product(db_session)
    provider = FakeProvider()
    configure(provider)
    state = connect(client, item.id)
    oauth = db_session.scalar(select(OAuthSession))
    oauth.platform = foreign_platform
    db_session.commit()
    response = callback(client, state, code=CODE)
    assert 400 <= response.status_code < 500
    assert provider.exchange_calls == provider.user_calls == 0
    assert db_session.scalar(select(func.count(SocialAccount.id))) == 0
    assert state not in response.text and CODE not in response.text


@pytest.mark.parametrize(
    ("callback_path", "provider_dependency"),
    [
        ("youtube", get_youtube_provider),
        ("instagram", get_instagram_provider),
        ("tiktok", get_tiktok_provider),
    ],
)
def test_other_platform_callbacks_cannot_consume_pinterest_state(
    client: TestClient,
    db_session: Session,
    callback_path: str,
    provider_dependency: object,
) -> None:
    item = product(db_session)
    pinterest = FakeProvider()
    configured = settings(
        enable_social_account_binding=True,
        enable_instagram_account_binding=True,
        enable_tiktok_account_binding=True,
    )
    configure(pinterest, configured)
    other_calls = 0

    def other_provider() -> object:
        nonlocal other_calls
        other_calls += 1
        return object()

    app.dependency_overrides[provider_dependency] = other_provider
    state = connect(client, item.id)
    response = client.get(
        f"/api/v1/social-accounts/{callback_path}/callback",
        params={"state": state, "code": CODE},
        follow_redirects=False,
    )
    assert 400 <= response.status_code < 500
    assert other_calls == 1  # dependency resolved, but no Provider method called
    assert pinterest.exchange_calls == pinterest.user_calls == 0
    assert db_session.scalar(select(func.count(SocialAccount.id))) == 0
    oauth = db_session.scalar(select(OAuthSession))
    assert oauth.consumed_at is None
    assert state not in response.text and CODE not in response.text


def test_scope_mismatch_fails_without_account(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    provider = FakeProvider(PINTEREST_SCOPES[:-1])
    configure(provider)
    response = callback(client, connect(client, item.id), code=CODE)
    assert response.headers["location"].endswith("?pinterest_oauth=failed")
    assert db_session.scalar(select(func.count(SocialAccount.id))) == 0


def test_expired_missing_cookie_and_replay_are_rejected(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    provider = FakeProvider()
    configure(provider)
    state = connect(client, item.id)
    oauth = db_session.scalar(select(OAuthSession))
    oauth.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert callback(client, state, code=CODE).status_code == 410
    state = connect(client, item.id)
    client.cookies.clear()
    assert callback(client, state, code=CODE).status_code == 400
    state = connect(client, item.id)
    assert callback(client, state, code=CODE).status_code == 303
    assert callback(client, state, code=CODE).status_code == 409


def test_same_product_reauthorization_updates_one_account(
    client: TestClient, db_session: Session
) -> None:
    item = product(db_session)
    provider = FakeProvider()
    configure(provider)
    callback(client, connect(client, item.id), code=CODE)
    callback(client, connect(client, item.id), code=CODE)
    assert db_session.scalar(select(func.count(SocialAccount.id))) == 1


def test_same_identity_isolated_between_products(
    client: TestClient, db_session: Session
) -> None:
    first, second = product(db_session, "first"), product(db_session, "second")
    provider = FakeProvider()
    configure(provider)
    callback(client, connect(client, first.id), code=CODE)
    callback(client, connect(client, second.id), code=CODE)
    accounts = list(db_session.scalars(select(SocialAccount)))
    assert len(accounts) == 2
    assert {account.product_id for account in accounts} == {first.id, second.id}


def test_product_isolation_and_local_disconnect_are_provider_free(
    client: TestClient, db_session: Session
) -> None:
    first, second = product(db_session, "one"), product(db_session, "two")
    provider = FakeProvider()
    configure(provider)
    callback(client, connect(client, first.id), code=CODE)
    account = db_session.scalar(select(SocialAccount))
    before = (provider.exchange_calls, provider.user_calls)
    wrong = client.post(
        f"/api/v1/social-accounts/pinterest/{account.id}/disconnect",
        json={"product_id": second.id, "confirm_disconnect": True},
    )
    assert wrong.status_code == 404
    response = client.post(
        f"/api/v1/social-accounts/pinterest/{account.id}/disconnect",
        json={"product_id": first.id, "confirm_disconnect": True},
    )
    assert response.status_code == 200 and response.json()["local_only"] is True
    db_session.refresh(account)
    assert account.connection_status == "DISCONNECTED"
    assert account.access_token_ciphertext is account.refresh_token_ciphertext is None
    assert before == (provider.exchange_calls, provider.user_calls)
