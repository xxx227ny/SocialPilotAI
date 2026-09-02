from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class YouTubeConnectRequest(BaseModel):
    product_id: int = Field(gt=0)


class YouTubeConnectRead(BaseModel):
    authorization_url: str
    expires_at: datetime


class InstagramConnectRequest(BaseModel):
    product_id: int = Field(gt=0)


class InstagramConnectRead(BaseModel):
    authorization_url: str
    expires_at: datetime


class TikTokConnectRequest(BaseModel):
    product_id: int = Field(gt=0)


class TikTokConnectRead(BaseModel):
    authorization_url: str
    expires_at: datetime


class PinterestConnectRequest(BaseModel):
    product_id: int = Field(gt=0)


class PinterestConnectRead(BaseModel):
    authorization_url: str
    expires_at: datetime


class SocialAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    platform: Literal["youtube", "instagram", "tiktok", "pinterest"]
    provider_account_id: str
    display_name: str
    scopes: list[str]
    connection_status: str
    token_expires_at: datetime | None
    refresh_token_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    disconnected_at: datetime | None


class WorkspaceSocialAccountRead(SocialAccountRead):
    product_name: str


class LocalDisconnectRequest(BaseModel):
    confirm_disconnect: Literal[True]


class LocalDisconnectRead(BaseModel):
    account: WorkspaceSocialAccountRead
    local_only: Literal[True] = True
    provider_authorization_revoked: Literal[False] = False


class DisconnectRequest(BaseModel):
    product_id: int = Field(gt=0)
    revoke_google_authorization: bool = False
    confirm_disconnect: Literal[True]


class DisconnectRead(BaseModel):
    account: SocialAccountRead
    google_authorization_revoked: bool


class InstagramDisconnectRequest(BaseModel):
    product_id: int = Field(gt=0)
    confirm_disconnect: Literal[True]


class InstagramDisconnectRead(BaseModel):
    account: SocialAccountRead
    local_only: Literal[True] = True
    meta_authorization_revoked: Literal[False] = False


class TikTokDisconnectRequest(BaseModel):
    product_id: int = Field(gt=0)
    confirm_disconnect: Literal[True]


class TikTokDisconnectRead(BaseModel):
    account: SocialAccountRead
    local_only: Literal[True] = True
    tiktok_authorization_revoked: Literal[False] = False


class PinterestDisconnectRequest(BaseModel):
    product_id: int = Field(gt=0)
    confirm_disconnect: Literal[True]


class PinterestDisconnectRead(BaseModel):
    account: SocialAccountRead
    local_only: Literal[True] = True
    pinterest_authorization_revoked: Literal[False] = False


class PublishArtifactCandidateRead(BaseModel):
    artifact_id: int
    render_task_id: int
    video_project_id: int
    copy_matrix_id: int | None
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


class InstagramMediaSpecificationRead(BaseModel):
    container: str
    video_codec: str
    fps: float
    duration_seconds: float
    width: int
    height: int
    audio_codec: str | None
    audio_sample_rate: int | None


class InstagramPublishingMetadata(BaseModel):
    social_account_id: int = Field(gt=0)
    artifact_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2200)
    tags: list[str] = Field(default_factory=list, max_length=30)
    privacy_status: Literal["public"] = "public"
    made_for_kids: Literal[False] = False
    synthetic_media: Literal[True] = True
    notify_subscribers: Literal[False] = False
    share_to_feed: bool

    @field_validator("title", "description")
    @classmethod
    def clean_instagram_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def clean_instagram_tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            tag = value.strip().lstrip("#").strip()
            if not tag:
                continue
            if any(character.isspace() for character in tag) or len(tag) > 100:
                raise ValueError("Instagram hashtags are invalid")
            identity = tag.casefold()
            if identity not in seen:
                cleaned.append(tag)
                seen.add(identity)
        return cleaned

    @model_validator(mode="after")
    def require_instagram_caption_contract(self) -> InstagramPublishingMetadata:
        if not self.title:
            raise ValueError("Local task label cannot be empty")
        hashtags = " ".join(f"#{tag}" for tag in self.tags)
        caption = "\n\n".join(part for part in (self.description, hashtags) if part)
        if len(caption) > 2200:
            raise ValueError("Instagram caption must be at most 2200 characters")
        return self


class InstagramSubmitPreflightRead(BaseModel):
    status: Literal["READY", "BLOCKED"]
    ready: bool
    missing_requirements: list[str]
    input_digest: str
    preflight_digest: str
    expires_at: datetime
    product_id: int
    social_account_id: int
    professional_account_id: str
    artifact_id: int
    render_task_id: int
    video_project_id: int
    copy_matrix_id: int
    marketing_strategy_id: int
    content_type: Literal["video/mp4", "video/quicktime"]
    size_bytes: int
    sha256: str
    safe_path_digest: str
    media: InstagramMediaSpecificationRead
    caption_length: int
    share_to_feed: bool
    provider_calls: Literal[0] = 0
    database_writes: Literal[0] = 0


class InstagramPublishRequest(InstagramPublishingMetadata):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=200)
    confirm_upload: Literal[True]


class TikTokCreatorInfoRequest(BaseModel):
    social_account_id: int = Field(gt=0)
    request_id: str = Field(min_length=16, max_length=128)


class TikTokCreatorInfoSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    social_account_id: int
    creator_username: str
    creator_nickname: str
    privacy_level_options: list[str]
    comment_disabled: bool
    duet_disabled: bool
    stitch_disabled: bool
    max_video_post_duration_sec: int
    fetched_at: datetime
    expires_at: datetime
    created_at: datetime


class TikTokMediaSpecificationRead(InstagramMediaSpecificationRead):
    bit_rate: int


class TikTokPublishingMetadata(BaseModel):
    social_account_id: int = Field(gt=0)
    creator_info_snapshot_id: int = Field(gt=0)
    artifact_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2200)
    tags: list[str] = Field(default_factory=list, max_length=30)
    privacy_status: str = Field(min_length=1, max_length=100)
    disable_comment: bool
    disable_duet: bool
    disable_stitch: bool
    brand_content_toggle: bool
    brand_organic_toggle: bool

    @field_validator("title", "description")
    @classmethod
    def clean_tiktok_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def clean_tiktok_tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = raw.strip().lstrip("#").strip()
            if not value:
                continue
            if any(character.isspace() for character in value) or len(value) > 100:
                raise ValueError("TikTok tags are invalid")
            if value.casefold() not in seen:
                seen.add(value.casefold())
                cleaned.append(value)
        return cleaned

    @model_validator(mode="after")
    def validate_tiktok_contract(self) -> TikTokPublishingMetadata:
        caption = " ".join(
            filter(None, [self.description, *[f"#{tag}" for tag in self.tags]])
        )
        if len(caption.encode("utf-16-le")) // 2 > 2200:
            raise ValueError("TikTok caption exceeds 2200 UTF-16 code units")
        if not self.brand_content_toggle and not self.brand_organic_toggle:
            raise ValueError("At least one TikTok disclosure must be selected")
        if self.brand_content_toggle and not self.brand_organic_toggle:
            raise ValueError("Branded content requires organic content disclosure")
        return self


class TikTokSubmitPreflightRead(BaseModel):
    status: Literal["READY", "BLOCKED"]
    ready: bool
    missing_requirements: list[str]
    input_digest: str
    preflight_digest: str
    expires_at: datetime
    product_id: int
    social_account_id: int
    creator_info_snapshot_id: int
    artifact_id: int
    render_task_id: int
    video_project_id: int
    copy_matrix_id: int
    marketing_strategy_id: int
    content_type: Literal["video/mp4", "video/quicktime"]
    size_bytes: int
    sha256: str
    safe_path_digest: str
    media: TikTokMediaSpecificationRead
    caption_length_utf16: int
    provider_calls: Literal[0] = 0
    database_writes: Literal[0] = 0


class TikTokPublishRequest(TikTokPublishingMetadata):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    confirm_upload: Literal[True]


class TikTokRefreshRequest(BaseModel):
    product_id: int = Field(gt=0)
    refresh_request_id: str = Field(min_length=16, max_length=128)


class InstagramFinalizePreflightRequest(BaseModel):
    product_id: int = Field(gt=0)


class InstagramFinalizePreflightRead(BaseModel):
    ready: Literal[True] = True
    product_id: int
    social_account_id: int
    publish_task_id: int
    input_digest: str
    preflight_digest: str
    expires_at: datetime
    provider_calls: Literal[0] = 0
    database_writes: Literal[0] = 0


class InstagramFinalizeRequest(BaseModel):
    product_id: int = Field(gt=0)
    finalize_request_id: str = Field(min_length=16, max_length=128)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    confirm_public_publish: Literal[True]


class YouTubePublishingMetadata(BaseModel):
    social_account_id: int = Field(gt=0)
    artifact_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    privacy_status: Literal["private"] = "private"
    made_for_kids: bool | None
    synthetic_media: Literal[True] = True
    notify_subscribers: Literal[False] = False

    @field_validator("title", "description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 100 for value in cleaned):
            raise ValueError("Each tag must be at most 100 characters")
        if len(",".join(cleaned)) > 500:
            raise ValueError("Combined tags must be at most 500 characters")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def require_title(self) -> YouTubePublishingMetadata:
        if not self.title:
            raise ValueError("Title cannot be empty")
        return self


class YouTubePreflightRead(BaseModel):
    status: Literal["READY", "BLOCKED"]
    ready: bool
    missing_requirements: list[str]
    input_digest: str
    preflight_digest: str
    expires_at: datetime
    product_id: int
    social_account_id: int
    channel_id: str
    artifact_id: int
    render_task_id: int
    video_project_id: int
    copy_matrix_id: int | None
    privacy_status: Literal["private"]
    synthetic_media: Literal[True]
    notify_subscribers: Literal[False]
    provider_calls: Literal[0] = 0
    database_writes: Literal[0] = 0


class YouTubePublishRequest(YouTubePublishingMetadata):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=200)
    confirm_upload: Literal[True]


class PublishTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    social_account_id: int
    artifact_id: int
    platform: Literal["youtube", "instagram", "tiktok"]
    title: str
    description: str
    tags: list[str]
    privacy_status: Literal["private", "public"]
    made_for_kids: bool
    synthetic_media: Literal[True]
    notify_subscribers: Literal[False]
    share_to_feed: bool
    status: str
    provider_video_id: str | None
    provider_publish_id: str | None
    safe_error_code: str | None
    uncertain: bool
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    completed_at: datetime | None
    disable_comment: bool
    disable_duet: bool
    disable_stitch: bool
    brand_content_toggle: bool
    brand_organic_toggle: bool


class PublishExecutionRead(BaseModel):
    task: PublishTaskRead
    reused: bool
    external_call: bool


class PublishTaskIdentityRequest(BaseModel):
    product_id: int = Field(gt=0)
    refresh_request_id: str = Field(min_length=16, max_length=128)
