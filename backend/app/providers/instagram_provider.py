from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

from app.core.config import Settings

INSTAGRAM_SCOPES = (
    "instagram_business_basic",
    "instagram_business_content_publish",
)
INSTAGRAM_ACCOUNT_TYPES = {"BUSINESS", "CREATOR", "MEDIA_CREATOR"}


class InstagramProviderError(Exception):
    def __init__(self, safe_error_code: str) -> None:
        self.safe_error_code = safe_error_code
        super().__init__(safe_error_code)


@dataclass(frozen=True, slots=True)
class InstagramShortToken:
    access_token: str
    user_id: str
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InstagramLongToken:
    access_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class InstagramProfessionalProfile:
    account_id: str
    username: str
    account_type: str


@dataclass(frozen=True, slots=True)
class InstagramReelContainer:
    container_id: str
    upload_uri: str


@dataclass(frozen=True, slots=True)
class InstagramContainerStatus:
    status: str


@dataclass(frozen=True, slots=True)
class InstagramPublishedReel:
    media_id: str


class InstagramProvider:
    """Instagram API with Instagram Login boundary; never logs provider payloads."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.app_id = (settings.instagram_app_id or "").strip()
        self.app_secret = (
            settings.instagram_app_secret.get_secret_value().strip()
            if settings.instagram_app_secret is not None
            else ""
        )
        self.redirect_uri = (settings.instagram_oauth_redirect_uri or "").strip()
        self.version = (settings.instagram_graph_api_version or "").strip()
        self.timeout = settings.instagram_request_timeout
        self.transport = transport
        parsed = urlparse(self.redirect_uri)
        if (
            not self.app_id
            or not self.app_secret
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not self.version
        ):
            raise InstagramProviderError("instagram_configuration_missing")

    def authorization_url(self, *, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.app_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": ",".join(INSTAGRAM_SCOPES),
                "state": state,
            }
        )
        return f"https://www.instagram.com/oauth/authorize?{query}"

    async def exchange_code(self, *, code: str) -> InstagramShortToken:
        payload = await self._request(
            "POST",
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
                "code": code,
            },
        )
        access_token = payload.get("access_token")
        user_id = payload.get("user_id")
        permissions = payload.get("permissions")
        if isinstance(permissions, str):
            scopes = tuple(
                part.strip() for part in permissions.split(",") if part.strip()
            )
        elif isinstance(permissions, list) and all(
            isinstance(item, str) for item in permissions
        ):
            scopes = tuple(permissions)
        else:
            scopes = ()
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(user_id, (str, int))
        ):
            raise InstagramProviderError("invalid_provider_response")
        return InstagramShortToken(access_token, str(user_id), scopes)

    async def exchange_long_lived_token(self, short_token: str) -> InstagramLongToken:
        payload = await self._request(
            "GET",
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": self.app_secret,
                "access_token": short_token,
            },
        )
        token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(expires_in, (int, float))
            or expires_in <= 0
        ):
            raise InstagramProviderError("invalid_provider_response")
        return InstagramLongToken(
            token, datetime.now(UTC) + timedelta(seconds=float(expires_in))
        )

    async def get_professional_profile(
        self, *, user_id: str, access_token: str
    ) -> InstagramProfessionalProfile:
        payload = await self._request(
            "GET",
            f"https://graph.instagram.com/{self.version}/{user_id}",
            params={"fields": "id,username,account_type"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        account_id = payload.get("id")
        username = payload.get("username")
        account_type = payload.get("account_type")
        if not all(
            isinstance(value, str) and value
            for value in (account_id, username, account_type)
        ):
            raise InstagramProviderError("invalid_provider_response")
        normalized_type = str(account_type).upper()
        if normalized_type not in INSTAGRAM_ACCOUNT_TYPES:
            raise InstagramProviderError("professional_account_required")
        return InstagramProfessionalProfile(
            str(account_id), str(username)[:255], normalized_type
        )

    async def create_resumable_reel_container(
        self,
        *,
        professional_account_id: str,
        access_token: str,
        caption: str,
        share_to_feed: bool,
    ) -> InstagramReelContainer:
        payload = await self._request(
            "POST",
            (
                f"https://graph.instagram.com/{self.version}/"
                f"{professional_account_id}/media"
            ),
            data={
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": caption,
                "share_to_feed": "true" if share_to_feed else "false",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        container_id = payload.get("id")
        upload_uri = payload.get("uri")
        if (
            not isinstance(container_id, str)
            or not container_id
            or not isinstance(upload_uri, str)
            or not upload_uri
        ):
            raise InstagramProviderError("invalid_provider_response")
        _validate_upload_uri(upload_uri)
        return InstagramReelContainer(container_id, upload_uri)

    async def upload_reel_bytes(
        self,
        *,
        upload_uri: str,
        access_token: str,
        path: Path,
        size_bytes: int,
    ) -> None:
        _validate_upload_uri(upload_uri)
        if (
            not path.is_absolute()
            or not path.is_file()
            or path.stat().st_size != size_bytes
        ):
            raise InstagramProviderError("instagram_upload_input_invalid")
        payload = await self._request(
            "POST",
            upload_uri,
            headers={
                "Authorization": f"Bearer {access_token}",
                "offset": "0",
                "file_size": str(size_bytes),
                "Content-Type": "application/octet-stream",
            },
            content=_file_chunks(path),
        )
        success = payload.get("success")
        if success not in {True, "true"}:
            raise InstagramProviderError("instagram_upload_rejected")

    async def get_container_status(
        self, *, container_id: str, access_token: str
    ) -> InstagramContainerStatus:
        payload = await self._request(
            "GET",
            f"https://graph.instagram.com/{self.version}/{container_id}",
            params={"fields": "status_code"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        value = payload.get("status_code")
        if not isinstance(value, str):
            raise InstagramProviderError("invalid_provider_response")
        status = value.upper()
        if status not in {"IN_PROGRESS", "FINISHED", "ERROR", "EXPIRED"}:
            raise InstagramProviderError("invalid_provider_response")
        return InstagramContainerStatus(status)

    async def publish_reel(
        self,
        *,
        professional_account_id: str,
        container_id: str,
        access_token: str,
    ) -> InstagramPublishedReel:
        payload = await self._request(
            "POST",
            (
                f"https://graph.instagram.com/{self.version}/"
                f"{professional_account_id}/media_publish"
            ),
            data={"creation_id": container_id},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        media_id = payload.get("id")
        if not isinstance(media_id, str) or not media_id:
            raise InstagramProviderError("invalid_provider_response")
        return InstagramPublishedReel(media_id)

    async def _request(
        self, method: str, url: str, **kwargs: object
    ) -> dict[str, object]:
        response: httpx.Response | None = None
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport
            ) as client:
                response = await client.request(method, url, **kwargs)
        except httpx.RequestError:
            pass
        if response is None:
            # Raise outside the except block so no sensitive request exception is
            # retained as __cause__ or __context__.
            raise InstagramProviderError("instagram_provider_unavailable")
        if response.status_code < 200 or response.status_code >= 300:
            raise InstagramProviderError("instagram_provider_rejected_request")
        payload: object | None = None
        with suppress(ValueError):
            payload = response.json()
        if not isinstance(payload, dict):
            raise InstagramProviderError("invalid_provider_response")
        return payload


def _validate_upload_uri(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "rupload.facebook.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise InstagramProviderError("instagram_upload_uri_invalid")


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            yield chunk
