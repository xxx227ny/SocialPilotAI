from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

import httpx

from app.core.config import Settings

PINTEREST_SCOPES = ("boards:read", "pins:read", "pins:write", "user_accounts:read")
PINTEREST_AUTHORIZE_URL = "https://www.pinterest.com/oauth/"
PINTEREST_TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
PINTEREST_USER_URL = "https://api.pinterest.com/v5/user_account"
MAX_ACCESS_TOKEN_SECONDS = 60 * 60 * 24 * 366
MAX_REFRESH_TOKEN_SECONDS = 60 * 60 * 24 * 366 * 10
EXPIRY_CLOCK_TOLERANCE_SECONDS = 300


class PinterestProviderError(Exception):
    def __init__(self, safe_error_code: str) -> None:
        self.safe_error_code = safe_error_code
        super().__init__(safe_error_code)


@dataclass(frozen=True, slots=True)
class PinterestToken:
    scopes: tuple[str, ...]
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str | None
    refresh_token_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class PinterestUser:
    account_id: str
    display_name: str
    account_type: str


class PinterestProvider:
    """Strict Pinterest OAuth boundary; provider bodies are never exposed."""

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.client_id = (settings.pinterest_client_id or "").strip()
        self.client_secret = (
            settings.pinterest_client_secret.get_secret_value().strip()
            if settings.pinterest_client_secret is not None
            else ""
        )
        self.redirect_uri = (settings.pinterest_oauth_redirect_uri or "").strip()
        self.timeout = settings.pinterest_request_timeout
        self.transport = transport
        if (
            not self.client_id
            or not self.client_secret
            or not _valid_redirect_uri(self.redirect_uri)
        ):
            raise PinterestProviderError("pinterest_configuration_missing")

    def authorization_url(self, *, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": ",".join(PINTEREST_SCOPES),
                "state": state,
            }
        )
        return f"{PINTEREST_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, *, code: str) -> PinterestToken:
        payload = await self._request(
            "POST",
            PINTEREST_TOKEN_URL,
            auth=httpx.BasicAuth(self.client_id, self.client_secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
        )
        return self._token(
            payload,
            expected_response_type="authorization_code",
            require_refresh=True,
        )

    async def refresh_access_token(self, refresh_token: str) -> PinterestToken:
        payload = await self._request(
            "POST",
            PINTEREST_TOKEN_URL,
            auth=httpx.BasicAuth(self.client_id, self.client_secret),
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        return self._token(
            payload,
            expected_response_type="refresh_token",
            require_refresh=True,
        )

    async def get_user_account(self, *, access_token: str) -> PinterestUser:
        payload = await self._request(
            "GET",
            PINTEREST_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        account_id = payload.get("id")
        username = payload.get("username")
        business_name = payload.get("business_name")
        account_type = payload.get("account_type")
        if (
            not isinstance(account_id, str)
            or not account_id
            or not isinstance(username, str)
            or not username
            or business_name is not None
            and not isinstance(business_name, str)
            or account_type not in {"BUSINESS", "PINNER"}
        ):
            raise PinterestProviderError("pinterest_invalid_provider_response")
        display = business_name.strip() if isinstance(business_name, str) else ""
        return PinterestUser(account_id, (display or username)[:255], account_type)

    def _token(
        self,
        payload: dict[str, object],
        *,
        expected_response_type: str,
        require_refresh: bool,
    ) -> PinterestToken:
        access = payload.get("access_token")
        token_type = payload.get("token_type")
        response_type = payload.get("response_type")
        scope = payload.get("scope")
        refresh = payload.get("refresh_token")
        if (
            not isinstance(access, str)
            or not access
            or not isinstance(token_type, str)
            or token_type.casefold() != "bearer"
            or not isinstance(scope, str)
            or response_type != expected_response_type
            or require_refresh
            and (not isinstance(refresh, str) or not refresh)
            or refresh is not None
            and (not isinstance(refresh, str) or not refresh)
        ):
            raise PinterestProviderError("pinterest_invalid_provider_response")
        scopes = tuple(
            part.strip() for part in scope.replace(" ", ",").split(",") if part.strip()
        )
        now = datetime.now(UTC)
        access_seconds = _positive_duration(
            payload.get("expires_in"), MAX_ACCESS_TOKEN_SECONDS
        )
        refresh_expiry = None
        if refresh is not None:
            refresh_expiry = _refresh_expiry(
                relative_value=payload.get("refresh_token_expires_in"),
                absolute_value=payload.get("refresh_token_expires_at"),
                now=now,
            )
        return PinterestToken(
            scopes,
            access,
            now + timedelta(seconds=access_seconds),
            refresh,
            refresh_expiry,
        )

    async def _request(
        self, method: str, url: str, **kwargs: object
    ) -> dict[str, object]:
        request_failed = False
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.request(method, url, **kwargs)
        except httpx.RequestError:
            request_failed = True
        if request_failed:
            raise PinterestProviderError("pinterest_provider_unavailable") from None
        if not 200 <= response.status_code < 300:
            raise PinterestProviderError("pinterest_provider_rejected_request")
        try:
            payload = response.json()
        except ValueError:
            raise PinterestProviderError(
                "pinterest_invalid_provider_response"
            ) from None
        if not isinstance(payload, dict):
            raise PinterestProviderError("pinterest_invalid_provider_response")
        return payload


def _valid_redirect_uri(value: str) -> bool:
    parsed = urlparse(value)
    return bool(
        parsed.scheme == "https"
        and parsed.netloc
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _positive_duration(value: object, maximum: int) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 < float(value) <= maximum
    ):
        raise PinterestProviderError("pinterest_invalid_token_expiry")
    return float(value)


def _refresh_expiry(
    *, relative_value: object, absolute_value: object, now: datetime
) -> datetime:
    relative_expiry: datetime | None = None
    absolute_expiry: datetime | None = None
    if relative_value is not None:
        seconds = _positive_duration(relative_value, MAX_REFRESH_TOKEN_SECONDS)
        relative_expiry = now + timedelta(seconds=seconds)
    if absolute_value is not None:
        if isinstance(absolute_value, bool) or not isinstance(
            absolute_value, (int, float)
        ):
            raise PinterestProviderError("pinterest_invalid_token_expiry")
        try:
            absolute_expiry = datetime.fromtimestamp(float(absolute_value), UTC)
        except (OverflowError, OSError, ValueError):
            raise PinterestProviderError("pinterest_invalid_token_expiry") from None
        remaining = (absolute_expiry - now).total_seconds()
        if not 0 < remaining <= MAX_REFRESH_TOKEN_SECONDS:
            raise PinterestProviderError("pinterest_invalid_token_expiry")
    if relative_expiry is None and absolute_expiry is None:
        raise PinterestProviderError("pinterest_invalid_token_expiry")
    if (
        relative_expiry is not None
        and absolute_expiry is not None
        and abs((relative_expiry - absolute_expiry).total_seconds())
        > EXPIRY_CLOCK_TOLERANCE_SECONDS
    ):
        raise PinterestProviderError("pinterest_token_expiry_mismatch")
    return absolute_expiry or relative_expiry  # type: ignore[return-value]
