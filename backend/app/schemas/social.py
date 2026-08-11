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


class SocialAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    platform: Literal["youtube", "instagram"]
    provider_account_id: str
    display_name: str
    scopes: list[str]
    connection_status: str
    token_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    disconnected_at: datetime | None


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


class PublishArtifactCandidateRead(BaseModel):
    artifact_id: int
    render_task_id: int
    video_project_id: int
    copy_matrix_id: int
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


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
    copy_matrix_id: int
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
    platform: Literal["youtube"]
    title: str
    description: str
    tags: list[str]
    privacy_status: Literal["private"]
    made_for_kids: bool
    synthetic_media: Literal[True]
    notify_subscribers: Literal[False]
    status: str
    provider_video_id: str | None
    safe_error_code: str | None
    uncertain: bool
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    completed_at: datetime | None


class PublishExecutionRead(BaseModel):
    task: PublishTaskRead
    reused: bool
    external_call: bool


class PublishTaskIdentityRequest(BaseModel):
    product_id: int = Field(gt=0)
    refresh_request_id: str = Field(min_length=16, max_length=128)
