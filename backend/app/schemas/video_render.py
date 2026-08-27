from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.video_render_artifact import VideoRenderArtifactSchema


class VideoRenderTaskCreate(BaseModel):
    scene_sequence: int = Field(gt=0)
    resolution: str = Field(default="720P", min_length=1, max_length=50)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("resolution", "idempotency_key")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("render task fields cannot be empty")
        return cleaned


class VideoRenderTaskDetails(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_project_id: int
    scene_sequence: int
    status: str
    provider_name: str | None
    provider_task_id: str | None
    render_prompt: str
    duration_seconds: int
    aspect_ratio: str
    resolution: str
    idempotency_key: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class VideoRenderTaskSchema(VideoRenderTaskDetails):
    external_call: Literal[False] = False


class VideoRenderExecutionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task: VideoRenderTaskDetails
    artifact: VideoRenderArtifactSchema | None = None
    external_call: bool


class VideoRenderTaskSafeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_project_id: int
    scene_sequence: int
    status: str
    provider_name: str | None
    duration_seconds: int
    aspect_ratio: str
    resolution: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    external_call: Literal[False] = False


class VideoRenderTaskPublicRead(VideoRenderTaskSafeRead):
    provider_task_id: None = None

    @field_validator("provider_task_id", mode="before")
    @classmethod
    def redact_provider_task_id(cls, value: object) -> None:
        del value
        return None


class VideoRenderArtifactReferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_render_task_id: int
    created_at: datetime
    updated_at: datetime


class VideoRenderArtifactSafeRead(VideoRenderArtifactReferenceRead):
    provider: str
    content_available: Literal[True] = True
    content_url: str
    download_url: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_kind: Literal["local_filesystem"] = "local_filesystem"


class VideoRenderRecoveryDecisionRead(BaseModel):
    category: Literal[
        "created",
        "submit_uncertain",
        "active",
        "refresh_uncertain",
        "terminal_failure",
        "artifact_persist_failed",
        "succeeded",
        "succeeded_artifact_unavailable",
    ]
    artifact_state: Literal[
        "not_applicable",
        "available",
        "missing",
        "invalid",
    ]
    read_only_retry_allowed: bool
    continue_original_submit_allowed: bool
    explicit_refresh_allowed: bool
    resubmit_forbidden: bool
    presentation_fallback_available: bool
    automatic_action_allowed: Literal[False] = False
    user_message: str


class VideoRenderOperationRead(BaseModel):
    video_project_id: int
    product_id: int
    marketing_strategy_id: int
    copy_matrix_id: int | None
    task: VideoRenderTaskSafeRead
    artifact: VideoRenderArtifactReferenceRead | None = None
    reused: bool
    external_call: bool
    recovered: bool = False
    recovery: VideoRenderRecoveryDecisionRead
    association_notice: str


class VideoRenderPreflightRead(BaseModel):
    video_project_id: int
    product_id: int
    marketing_strategy_id: int
    copy_matrix_id: int | None
    input_ready: bool
    provider: Literal["Wanx"] = "Wanx"
    provider_configured: bool
    execution_enabled: bool
    artifact_storage_configured: bool
    contract_ready: bool
    ready_for_execution: bool
    missing_requirements: list[str]
    platform: str
    duration_seconds: int
    aspect_ratio: str
    scene_count: int
    project_status: str
    scene_sequence: Literal[1] = 1
    resolution: Literal["720P"] = "720P"
    provider_model: str
    render_contract_version: str
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime
    preflight_only: Literal[True] = True
    estimated_cost_notice: str
    association_notice: str


class VideoRenderSubmitJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    marketing_strategy_id: int = Field(gt=0)
    copy_matrix_id: int | None = Field(default=None, gt=0)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    cost_confirmed: Literal[True]
    render_mode: Literal["scene", "product_reference"] = "scene"
    reference_product_asset_id: int | None = Field(default=None, gt=0)
    reference_product_asset_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    @field_validator("preflight_expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("preflight_expires_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_reference_identity(self) -> "VideoRenderSubmitJobRequest":
        has_id = self.reference_product_asset_id is not None
        has_sha = self.reference_product_asset_sha256 is not None
        if has_id != has_sha:
            raise ValueError("Reference asset id and digest must be supplied together")
        if self.render_mode == "product_reference" and not has_id:
            raise ValueError("Product-reference rendering requires an exact asset")
        if self.render_mode == "scene" and has_id:
            raise ValueError("Scene rendering cannot include a product reference asset")
        return self


class VideoRenderRefreshJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    video_project_id: int = Field(gt=0)
    refresh_request_id: str = Field(
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class LiveVideoRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_live_generation: Literal[True]
