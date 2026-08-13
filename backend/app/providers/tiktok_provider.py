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
TIKTOK_CREATOR_INFO_URL = (
    "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
)
TIKTOK_VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
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


@dataclass(frozen=True, slots=True)
class TikTokCreatorInfo:
    creator_username: str
    creator_nickname: str
    privacy_level_options: tuple[str, ...]
    comment_disabled: bool
    duet_disabled: bool
    stitch_disabled: bool
    max_video_post_duration_sec: int


@dataclass(frozen=True, slots=True)
class TikTokDirectPostSession:
    publish_id: str
    upload_url: str


@dataclass(frozen=True, slots=True)
class TikTokPublishStatus:
    status: str


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

    async def refresh_access_token(self, refresh_token: str) -> TikTokToken:
        payload = await self._request(
            "POST",
            TIKTOK_TOKEN_URL,
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        return self._token(payload)

    async def query_creator_info(self, *, access_token: str) -> TikTokCreatorInfo:
        payload = await self._request(
            "POST", TIKTOK_CREATOR_INFO_URL, json={}, headers=self._auth(access_token)
        )
        data = self._ok_data(payload)
        options = data.get("privacy_level_options")
        duration = data.get("max_video_post_duration_sec")
        booleans = [
            data.get(name)
            for name in ("comment_disabled", "duet_disabled", "stitch_disabled")
        ]
        if (
            not isinstance(data.get("creator_username"), str)
            or not data["creator_username"]
            or not isinstance(data.get("creator_nickname"), str)
            or not data["creator_nickname"]
            or not isinstance(options, list)
            or not options
            or not all(isinstance(value, str) and value for value in options)
            or not all(isinstance(value, bool) for value in booleans)
            or isinstance(duration, bool)
            or not isinstance(duration, int)
            or not 3 <= duration <= 600
        ):
            raise TikTokProviderError("tiktok_invalid_provider_response")
        return TikTokCreatorInfo(
            creator_username=data["creator_username"][:255],
            creator_nickname=data["creator_nickname"][:255],
            privacy_level_options=tuple(dict.fromkeys(options)),
            comment_disabled=booleans[0],
            duet_disabled=booleans[1],
            stitch_disabled=booleans[2],
            max_video_post_duration_sec=duration,
        )

    async def initialize_direct_post(
        self,
        *,
        access_token: str,
        caption: str,
        privacy_level: str,
        disable_comment: bool,
        disable_duet: bool,
        disable_stitch: bool,
        brand_content_toggle: bool,
        brand_organic_toggle: bool,
        size_bytes: int,
        chunk_size: int,
        total_chunks: int,
    ) -> TikTokDirectPostSession:
        payload = await self._request(
            "POST",
            TIKTOK_VIDEO_INIT_URL,
            headers=self._auth(access_token),
            json={
                "post_info": {
                    "title": caption,
                    "privacy_level": privacy_level,
                    "disable_comment": disable_comment,
                    "disable_duet": disable_duet,
                    "disable_stitch": disable_stitch,
                    "brand_content_toggle": brand_content_toggle,
                    "brand_organic_toggle": brand_organic_toggle,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size_bytes,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunks,
                },
            },
        )
        data = self._ok_data(payload)
        publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
        if (
            not isinstance(publish_id, str)
            or not publish_id
            or not _safe_upload_url(upload_url)
        ):
            raise TikTokProviderError("tiktok_invalid_provider_response")
        return TikTokDirectPostSession(publish_id, upload_url)

    async def upload_video_chunk(
        self,
        *,
        upload_url: str,
        content: bytes,
        start: int,
        end: int,
        total: int,
        content_type: str = "video/mp4",
    ) -> None:
        if (
            not _safe_upload_url(upload_url)
            or end - start + 1 != len(content)
            or content_type not in {"video/mp4", "video/quicktime"}
        ):
            raise TikTokProviderError("tiktok_upload_contract_invalid")
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.put(
                    upload_url,
                    content=content,
                    headers={
                        "Content-Type": content_type,
                        "Content-Length": str(len(content)),
                        "Content-Range": f"bytes {start}-{end}/{total}",
                    },
                )
        except httpx.RequestError as exc:
            raise TikTokProviderError("tiktok_upload_result_uncertain") from exc
        if not 200 <= response.status_code < 300:
            raise TikTokProviderError("tiktok_upload_result_uncertain")

    async def fetch_publish_status(
        self, *, access_token: str, publish_id: str
    ) -> TikTokPublishStatus:
        payload = await self._request(
            "POST",
            TIKTOK_STATUS_URL,
            headers=self._auth(access_token),
            json={"publish_id": publish_id},
        )
        value = self._ok_data(payload).get("status")
        if value not in {
            "PROCESSING_UPLOAD",
            "PROCESSING_DOWNLOAD",
            "SEND_TO_USER_INBOX",
            "PUBLISH_COMPLETE",
            "FAILED",
        }:
            raise TikTokProviderError("tiktok_unknown_publish_status")
        return TikTokPublishStatus(value)

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    @staticmethod
    def _ok_data(payload: dict[str, object]) -> dict[str, object]:
        error, data = payload.get("error"), payload.get("data")
        if (
            not isinstance(error, dict)
            or error.get("code") != "ok"
            or not isinstance(data, dict)
        ):
            raise TikTokProviderError("tiktok_invalid_provider_response")
        return data

    def _token(self, payload: dict[str, object]) -> TikTokToken:
        values = {
            name: payload.get(name)
            for name in (
                "open_id",
                "scope",
                "access_token",
                "refresh_token",
                "token_type",
            )
        }
        if (
            not all(isinstance(value, str) and value for value in values.values())
            or values["token_type"].casefold() != "bearer"
        ):
            raise TikTokProviderError("tiktok_invalid_provider_response")
        now = datetime.now(UTC)
        return TikTokToken(
            values["open_id"],
            tuple(x.strip() for x in values["scope"].split(",") if x.strip()),
            values["access_token"],
            now
            + timedelta(
                seconds=_positive_duration(
                    payload.get("expires_in"), MAX_ACCESS_TOKEN_SECONDS
                )
            ),
            values["refresh_token"],
            now
            + timedelta(
                seconds=_positive_duration(
                    payload.get("refresh_expires_in"), MAX_REFRESH_TOKEN_SECONDS
                )
            ),
        )

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


def _safe_upload_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    return bool(
        parsed.scheme == "https"
        and host
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and (
            host == "tiktokapis.com"
            or host.endswith(".tiktokapis.com")
            or host == "tiktokcdn.com"
            or host.endswith(".tiktokcdn.com")
        )
    )
