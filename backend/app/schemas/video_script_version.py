from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictScriptModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StoryboardSceneDraft(StrictScriptModel):
    sequence: int = Field(ge=1, le=12)
    start_ms: int = Field(ge=0, le=15000)
    end_ms: int = Field(gt=0, le=15000)
    shot_type: str = Field(min_length=1, max_length=120)
    visual_description: str = Field(min_length=1, max_length=2000)
    action_description: str = Field(default="", max_length=1200)
    narration: str = Field(min_length=1, max_length=2000)
    subtitle_draft: str = Field(min_length=1, max_length=2000)

    @field_validator("shot_type", "visual_description", "narration", "subtitle_draft")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("scene text cannot be empty")
        return cleaned

    @field_validator("action_description")
    @classmethod
    def normalize_optional(cls, value: str) -> str:
        return " ".join(value.split())


class VideoScriptDraftRequest(StrictScriptModel):
    source_type: Literal["MANUAL", "VIDEO_PROJECT_IMPORT"]
    idempotency_key: str = Field(
        min_length=8, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$"
    )
    parent_version_id: int | None = Field(default=None, gt=0)
    strategy_id: int | None = Field(default=None, gt=0)
    copy_matrix_id: int | None = Field(default=None, gt=0)
    source_video_project_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=300)
    concept: str = Field(min_length=1, max_length=2000)
    hook: str = Field(min_length=1, max_length=1000)
    cta: str = Field(min_length=1, max_length=1000)
    scenes: list[StoryboardSceneDraft] = Field(min_length=1, max_length=12)

    @field_validator("title", "concept", "hook", "cta")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("script text cannot be empty")
        return cleaned

    @model_validator(mode="after")
    def source_contract(self) -> "VideoScriptDraftRequest":
        if self.source_type == "MANUAL" and self.source_video_project_id is not None:
            raise ValueError("manual versions cannot identify a source VideoProject")
        if (
            self.source_type == "VIDEO_PROJECT_IMPORT"
            and self.source_video_project_id is None
        ):
            raise ValueError("VideoProject import requires an exact source id")
        return self


class VideoScriptPreflightRead(StrictScriptModel):
    ready: Literal[True]
    variant_id: int
    variant_source_digest: str
    product_id: int
    product_content_digest: str
    strategy_id: int | None
    strategy_digest: str | None
    copy_matrix_id: int | None
    target_platform_copy_digest: str | None
    source_video_project_id: int | None
    source_video_project_digest: str | None
    brand_kit_version_id: int | None
    brand_kit_version_digest: str | None
    platform: str
    language: str
    creative_angle: str | None
    source_digest: str
    content_digest: str
    preflight_digest: str
    expires_at: datetime
    full_narration: str
    full_subtitle_draft: str
    current_stage_cost: Decimal
    cost_scope: Literal["manual_versioning_only"]
    provider_call_count: Literal[0]
    review_status: Literal["UNREVIEWED"]
    database_writes: Literal[0]


class VideoScriptCreateRequest(VideoScriptDraftRequest):
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime


class StoryboardSceneRead(StrictScriptModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    video_script_version_id: int
    sequence: int
    start_ms: int
    end_ms: int
    shot_type: str
    visual_description: str
    action_description: str
    narration: str
    subtitle_draft: str


class VideoScriptVersionRead(StrictScriptModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    batch_video_variant_id: int
    version_number: int
    parent_version_id: int | None
    source_type: str
    source_digest: str
    content_digest: str
    idempotency_key: str
    product_id: int
    product_content_digest: str
    strategy_id: int | None
    strategy_digest: str | None
    copy_matrix_id: int | None
    target_platform_copy_digest: str | None
    source_video_project_id: int | None
    source_video_project_digest: str | None
    platform: str
    language: str
    creative_angle: str | None
    brand_kit_version_id: int | None
    brand_kit_version_digest: str | None
    title: str
    concept: str
    hook: str
    full_narration: str
    cta: str
    full_subtitle_draft: str
    created_by_kind: str
    source_execution_job_id: int | None
    prompt_snapshot_json: dict[str, object] | None
    prompt_digest: str | None
    provider_name: str | None
    provider_model: str | None
    provider_response_digest: str | None
    review_status: Literal["UNREVIEWED"]
    created_at: datetime
    scenes: list[StoryboardSceneRead]
    is_active: bool = False


class VideoScriptCreateRead(StrictScriptModel):
    version: VideoScriptVersionRead
    reused: bool


class VideoScriptActivateRead(StrictScriptModel):
    variant_id: int
    active_script_version_id: int
    editing_state: Literal["ACTIVE_VERSION"]
    reused: bool


class QwenScriptPreflightRequest(StrictScriptModel):
    idempotency_key: str = Field(
        min_length=8, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$"
    )
    strategy_id: int = Field(gt=0)
    copy_matrix_id: int | None = Field(default=None, gt=0)
    parent_version_id: int | None = Field(default=None, gt=0)


class QwenScriptPreflightRead(StrictScriptModel):
    ready_for_execution: bool
    variant_id: int
    variant_source_digest: str
    product_id: int
    product_content_digest: str
    strategy_id: int
    strategy_digest: str
    copy_matrix_id: int | None
    target_platform_copy_digest: str | None
    parent_version_id: int | None
    parent_content_digest: str | None
    brand_kit_version_id: int | None
    brand_kit_version_digest: str | None
    platform: str
    language: str
    creative_angle: str | None
    duration_ms: Literal[15000]
    aspect_ratio: Literal["9:16"]
    prompt_contract_version: str
    output_schema_version: str
    provider_name: Literal["qwen"]
    provider_model: str
    frozen_input_digest: str
    preflight_digest: str
    expires_at: datetime
    estimated_provider_calls: Literal[1]
    estimated_cost_min: Decimal | None
    estimated_cost_max: Decimal | None
    currency: str
    cost_estimate_basis: str | None
    cost_scope: Literal["single_qwen_video_script_generation"]
    requires_cost_confirmation: Literal[True]
    will_auto_activate: Literal[False]
    provider_call_count: Literal[0]
    database_writes: Literal[0]
    quota_limit: int
    quota_reserved: int
    quota_remaining: int


class QwenScriptJobCreateRequest(QwenScriptPreflightRequest):
    frozen_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    estimated_cost_min: Decimal = Field(ge=0)
    estimated_cost_max: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    cost_estimate_basis: str = Field(min_length=1, max_length=200)
    cost_confirmed: Literal[True]


class QwenGeneratedScene(StoryboardSceneDraft):
    pass


class QwenScriptProviderOutput(StrictScriptModel):
    title: str = Field(min_length=1, max_length=300)
    concept: str = Field(min_length=1, max_length=2000)
    hook: str = Field(min_length=1, max_length=1000)
    cta: str = Field(min_length=1, max_length=1000)
    scenes: list[QwenGeneratedScene] = Field(min_length=1, max_length=12)

    @field_validator("title", "concept", "hook", "cta")
    @classmethod
    def normalize_provider_text(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("provider script text cannot be empty")
        return cleaned


class QwenScriptJobInput(StrictScriptModel):
    variant_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=200)
    strategy_id: int = Field(gt=0)
    copy_matrix_id: int | None = Field(default=None, gt=0)
    parent_version_id: int | None = Field(default=None, gt=0)
    frozen_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    estimated_cost_min: Decimal = Field(ge=0)
    estimated_cost_max: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    cost_estimate_basis: str = Field(min_length=1, max_length=200)
    provider_model: str = Field(min_length=1, max_length=120)
