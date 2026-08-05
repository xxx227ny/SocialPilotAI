from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.core.config import Settings

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_SCOPES = (YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE)
CONNECT_ATTEMPT_LIMIT = 2


class YouTubeProviderError(Exception):
    def __init__(
        self,
        safe_error_code: str,
        *,
        status_code: int | None = None,
        uncertain: bool = False,
    ) -> None:
        self.safe_error_code = safe_error_code
        self.status_code = status_code
        self.uncertain = uncertain
        super().__init__(safe_error_code)


class YouTubeUploadUncertain(YouTubeProviderError):
    def __init__(self, session_uri: str) -> None:
        self.session_uri = session_uri
        super().__init__("upload_media_result_uncertain", uncertain=True)


@dataclass(frozen=True, slots=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class YouTubeChannel:
    channel_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class YouTubeUploadResult:
    video_id: str


@dataclass(frozen=True, slots=True)
class YouTubeVideoStatus:
    status: str
    safe_error_code: str | None = None


class YouTubeProvider:
    """Minimal official Google OAuth and YouTube Data API v3 client."""

    def __init__(self, settings: Settings) -> None:
        self.client_id = (settings.google_oauth_client_id or "").strip()
        self.client_secret = (
            settings.google_oauth_client_secret.get_secret_value()
            if settings.google_oauth_client_secret is not None
            else ""
        ).strip()
        self.redirect_uri = (settings.google_oauth_redirect_uri or "").strip()
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            raise YouTubeProviderError("oauth_configuration_missing")
        self.timeout = settings.youtube_request_timeout

    def authorization_url(
        self, *, state: str, code_challenge: str
    ) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(YOUTUBE_SCOPES),
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> OAuthTokens:
        payload = await self._form_post(
            "https://oauth2.googleapis.com/token",
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            },
            phase="token_exchange",
        )
        return self._tokens(payload)

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        payload = await self._form_post(
            "https://oauth2.googleapis.com/token",
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            phase="token_refresh",
        )
        return self._tokens(payload, fallback_refresh_token=refresh_token)

    async def get_channel(self, access_token: str) -> YouTubeChannel:
        payload = await self._json_request(
            "GET",
            "https://www.googleapis.com/youtube/v3/channels",
            access_token,
            params={"part": "id,snippet", "mine": "true", "maxResults": "1"},
            phase="channel_lookup",
        )
        items = payload.get("items")
        if not isinstance(items, list) or len(items) != 1:
            raise YouTubeProviderError("channel_not_found")
        item = items[0]
        if not isinstance(item, dict):
            raise YouTubeProviderError("invalid_provider_response")
        snippet = item.get("snippet")
        channel_id = item.get("id")
        title = snippet.get("title") if isinstance(snippet, dict) else None
        if not isinstance(channel_id, str) or not isinstance(title, str):
            raise YouTubeProviderError("invalid_provider_response")
        return YouTubeChannel(channel_id=channel_id, display_name=title[:255])

    async def revoke_token(self, token: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    data={"token": token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.RequestError as exc:
            raise YouTubeProviderError("revocation_failed", uncertain=True) from exc
        if response.status_code != 200:
            raise YouTubeProviderError(
                "revocation_failed", status_code=response.status_code
            )

    async def upload_video(
        self,
        *,
        access_token: str,
        path: Path,
        content_type: str,
        title: str,
        description: str,
        tags: list[str],
        made_for_kids: bool,
    ) -> YouTubeUploadResult:
        size = path.stat().st_size
        metadata = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": made_for_kids,
                "containsSyntheticMedia": True,
            },
        }
        headers = self._auth(access_token) | {
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": content_type,
        }
        try:
            initiated = await self._post_with_connect_retry(
                "https://www.googleapis.com/upload/youtube/v3/videos",
                params={
                    "uploadType": "resumable",
                    "part": "snippet,status",
                    "notifySubscribers": "false",
                },
                headers=headers,
                json=metadata,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise YouTubeProviderError(
                "upload_session_connection_failed", uncertain=False
            ) from exc
        except httpx.RequestError as exc:
            raise YouTubeProviderError(
                "upload_session_response_failed", uncertain=False
            ) from exc
        self._raise_for_status(initiated, phase="upload_session")
        session_uri = initiated.headers.get("location")
        if not session_uri:
            raise YouTubeProviderError("invalid_provider_response")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                uploaded = await client.put(
                    session_uri,
                    headers=self._auth(access_token)
                    | {"Content-Length": str(size), "Content-Type": content_type},
                    content=_file_chunks(path),
                )
        except httpx.RequestError as exc:
            raise YouTubeUploadUncertain(session_uri) from exc
        if uploaded.status_code in {408, 429} or uploaded.status_code >= 500:
            raise YouTubeUploadUncertain(session_uri)
        self._raise_for_status(uploaded, phase="upload_media")
        try:
            payload = uploaded.json()
        except ValueError as exc:
            raise YouTubeUploadUncertain(session_uri) from exc
        video_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(video_id, str) or not video_id:
            raise YouTubeUploadUncertain(session_uri)
        return YouTubeUploadResult(video_id=video_id)

    async def get_video_status(
        self, *, access_token: str, video_id: str
    ) -> YouTubeVideoStatus:
        payload = await self._json_request(
            "GET",
            "https://www.googleapis.com/youtube/v3/videos",
            access_token,
            params={"part": "status", "id": video_id},
            phase="status_refresh",
        )
        items = payload.get("items")
        if not isinstance(items, list) or len(items) != 1:
            return YouTubeVideoStatus("FAILED", "video_not_found")
        item = items[0]
        status = item.get("status") if isinstance(item, dict) else None
        upload_status = status.get("uploadStatus") if isinstance(status, dict) else None
        if upload_status == "processed":
            return YouTubeVideoStatus("SUCCEEDED")
        if upload_status in {"uploaded", "processing"}:
            return YouTubeVideoStatus("PROCESSING")
        return YouTubeVideoStatus("FAILED", "provider_processing_failed")

    async def _form_post(
        self, url: str, data: dict[str, str], *, phase: str
    ) -> dict[str, object]:
        try:
            response = await self._post_with_connect_retry(url, data=data)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise YouTubeProviderError(f"{phase}_connection_failed") from exc
        except httpx.RequestError as exc:
            raise YouTubeProviderError(f"{phase}_response_failed") from exc
        self._raise_for_status(response, phase=phase)
        try:
            payload = response.json()
        except ValueError as exc:
            raise YouTubeProviderError("invalid_provider_response") from exc
        if not isinstance(payload, dict):
            raise YouTubeProviderError("invalid_provider_response")
        return payload

    async def _json_request(
        self,
        method: str,
        url: str,
        access_token: str,
        *,
        params: dict[str, str],
        phase: str,
    ) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method, url, params=params, headers=self._auth(access_token)
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise YouTubeProviderError(f"{phase}_connection_failed") from exc
        except httpx.RequestError as exc:
            raise YouTubeProviderError(f"{phase}_response_failed") from exc
        self._raise_for_status(response, phase=phase)
        try:
            payload = response.json()
        except ValueError as exc:
            raise YouTubeProviderError("invalid_provider_response") from exc
        if not isinstance(payload, dict):
            raise YouTubeProviderError("invalid_provider_response")
        return payload

    @staticmethod
    def _auth(access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    async def _post_with_connect_retry(
        self, url: str, **kwargs: object
    ) -> httpx.Response:
        for attempt in range(CONNECT_ATTEMPT_LIMIT):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    return await client.post(url, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt + 1 == CONNECT_ATTEMPT_LIMIT:
                    raise
        raise RuntimeError("unreachable connection retry state")

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, phase: str) -> None:
        if response.is_success:
            return
        status = response.status_code
        base_code = {
            400: "invalid_request",
            401: "authentication_failed",
            403: "permission_denied",
            404: "not_found",
            408: "request_timeout",
            429: "rate_limited",
        }.get(status, "provider_service_error" if status >= 500 else "failed")
        raise YouTubeProviderError(
            f"{phase}_{base_code}", status_code=status
        )

    @staticmethod
    def _tokens(
        payload: dict[str, object], *, fallback_refresh_token: str | None = None
    ) -> OAuthTokens:
        access = payload.get("access_token")
        refresh = payload.get("refresh_token", fallback_refresh_token)
        expires_in = payload.get("expires_in")
        scope = payload.get("scope", " ".join(YOUTUBE_SCOPES))
        if not isinstance(access, str) or not access:
            raise YouTubeProviderError("invalid_provider_response")
        expires_at = None
        if isinstance(expires_in, (int, float)):
            expires_at = datetime.now(UTC) + timedelta(seconds=float(expires_in))
        scopes = tuple(str(scope).split())
        return OAuthTokens(
            access_token=access,
            refresh_token=refresh if isinstance(refresh, str) else None,
            expires_at=expires_at,
            scopes=scopes,
        )


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(256 * 1024):
            yield chunk
