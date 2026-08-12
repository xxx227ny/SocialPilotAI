from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

import httpx

from app.core.config import Settings

TIKTOK_SCOPES = ("user.info.basic", "video.publish")
TIKTOK_AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
MAX_ACCESS_TOKEN_SECONDS = 60 * 60 * 24 * 366
MAX_REFRESH_TOKEN_SECONDS = 60 * 60 * 24 * 366 * 10


class TikTokProviderError(Exception):
    def __init__(self, safe_error_code: str) -> None:
        self.safe_error_code = safe_error_code
        super().__init__(safe_error_code)


@dataclass(frozen=True, slots=True)
class TikTokToken:
    open_id: str
    scopes: tuple[str, ...]
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime


@dataclass(frozen=True, slots=True)
class TikTokUser:
    open_id: str
    display_name: str


class TikTokProvider:
    """Strict Web Login Kit boundary; provider bodies are never exposed."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client_key = (settings.tiktok_client_key or "").strip()
        self.client_secret = (
            settings.tiktok_client_secret.get_secret_value().strip()
            if settings.tiktok_client_secret is not None
            else ""
        )
        self.redirect_uri = (settings.tiktok_oauth_redirect_uri or "").strip()
        self.timeout = settings.tiktok_request_timeout
        self.transport = transport
        if (
            not self.client_key
            or not self.client_secret
            or not _valid_redirect_uri(self.redirect_uri)
        ):
            raise TikTokProviderError("tiktok_configuration_missing")

    def authorization_url(self, *, state: str) -> str:
        query = urlencode(
            {
                "client_key": self.client_key,
                "response_type": "code",
                "scope": ",".join(TIKTOK_SCOPES),
                "redirect_uri": self.redirect_uri,
                "state": state,
                "disable_auto_auth": "1",
            }
        )
        return f"{TIKTOK_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, *, code: str) -> TikTokToken:
        payload = await self._request(
            "POST",
            TIKTOK_TOKEN_URL,
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            },
        )
        required_strings = {
            name: payload.get(name)
            for name in (
                "open_id",
                "scope",
                "access_token",
                "refresh_token",
                "token_type",
            )
        }
        if not all(
            isinstance(value, str) and value for value in required_strings.values()
        ):
            raise TikTokProviderError("tiktok_invalid_provider_response")
        if required_strings["token_type"].casefold() != "bearer":
            raise TikTokProviderError("tiktok_invalid_token_type")
        access_seconds = _positive_duration(
            payload.get("expires_in"), MAX_ACCESS_TOKEN_SECONDS
        )
        refresh_seconds = _positive_duration(
            payload.get("refresh_expires_in"), MAX_REFRESH_TOKEN_SECONDS
        )
        scopes = tuple(
            part.strip()
            for part in required_strings["scope"].split(",")
            if part.strip()
        )
        now = datetime.now(UTC)
        return TikTokToken(
            open_id=required_strings["open_id"],
            scopes=scopes,
            access_token=required_strings["access_token"],
            access_token_expires_at=now + timedelta(seconds=access_seconds),
            refresh_token=required_strings["refresh_token"],
            refresh_token_expires_at=now + timedelta(seconds=refresh_seconds),
        )

    async def get_user(self, *, access_token: str) -> TikTokUser:
        payload = await self._request(
            "GET",
            TIKTOK_USER_INFO_URL,
            params={"fields": "open_id,display_name"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        error = payload.get("error")
        data = payload.get("data")
        user = data.get("user") if isinstance(data, dict) else None
        if (
            not isinstance(error, dict)
            or error.get("code") != "ok"
            or not isinstance(user, dict)
            or not isinstance(user.get("open_id"), str)
            or not user["open_id"]
            or not isinstance(user.get("display_name"), str)
            or not user["display_name"]
        ):
            raise TikTokProviderError("tiktok_invalid_provider_response")
        return TikTokUser(user["open_id"], user["display_name"][:255])

    async def _request(
        self, method: str, url: str, **kwargs: object
    ) -> dict[str, object]:
        request_failed = False
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.request(method, url, **kwargs)
        except httpx.RequestError:
            request_failed = True
        if request_failed:
            raise TikTokProviderError("tiktok_provider_unavailable") from None
        if response.status_code < 200 or response.status_code >= 300:
            raise TikTokProviderError("tiktok_provider_rejected_request")
        invalid_json = False
        try:
            payload = response.json()
        except ValueError:
            invalid_json = True
            payload = None
        if invalid_json:
            raise TikTokProviderError("tiktok_invalid_provider_response")
        if not isinstance(payload, dict):
            raise TikTokProviderError("tiktok_invalid_provider_response")
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
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TikTokProviderError("tiktok_invalid_token_expiry")
    duration = float(value)
    if duration <= 0 or duration > maximum:
        raise TikTokProviderError("tiktok_invalid_token_expiry")
    return duration
