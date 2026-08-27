from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.execution import ExecutionJobRead


class ProductImageShotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: int = Field(gt=0)
    product_asset_id: int = Field(gt=0)
    product_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    motion: str = Field(pattern=r"^(zoom_in|zoom_out|pan_left|pan_right)$")


class ProductVideoPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_id: int = Field(gt=0)
    script_version_id: int = Field(gt=0)
    platform: str = Field(pattern=r"^(TIKTOK|YOUTUBE_SHORTS|INSTAGRAM_REELS)$")
    shots: list[ProductImageShotRequest] = Field(min_length=1, max_length=12)


class ProductImageRenderSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_project_id: int = Field(gt=0)
    scene_sequence: int = Field(ge=1, le=12)
    product_asset_id: int = Field(gt=0)
    product_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    motion: str = Field(pattern=r"^(zoom_in|zoom_out|pan_left|pan_right)$")
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class WanxProductImageSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script_version_id: int = Field(gt=0)
    scene_sequence: int = Field(ge=1, le=12)
    reference_product_asset_id: int = Field(gt=0)
    reference_product_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    cost_confirmed: bool


class VoiceoverSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    composition_id: int = Field(gt=0)
    script_version_id: int = Field(gt=0)
    language: str = Field(min_length=2, max_length=35)
    voice: str = Field(min_length=1, max_length=120)
    speaking_rate: float = Field(default=1.0, ge=0.75, le=1.25)
    narration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)


class HappyHorseReferenceImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_asset_id: int = Field(gt=0)
    product_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HappyHorseVideoPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_project_id: int = Field(gt=0)
    script_version_id: int = Field(gt=0)
    reference_images: list[HappyHorseReferenceImage] = Field(min_length=1, max_length=9)


class HappyHorseVideoPreflightRead(HappyHorseVideoPreflightRequest):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime
    provider: str = "happyhorse"
    provider_model: str
    duration_seconds: int = 15
    aspect_ratio: str = "9:16"
    resolution: str = "720P"
    estimated_cost: str
    currency: str = "CNY"
    ready: bool
    missing_requirements: list[str]


class HappyHorseVideoSubmitRequest(HappyHorseVideoPreflightRequest):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    cost_confirmed: bool


class HappyHorseVideoRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_project_id: int = Field(gt=0)
    refresh_request_id: str = Field(min_length=16, max_length=128)


class ProductVideoPrepareRead(BaseModel):
    video_project_id: int
    script_version_id: int
    reused: bool
    input_digest: str
    shots: list[ProductImageShotRequest]
    tts_notice: str = "千问云配音"


class ProductVideoSceneRead(BaseModel):
    id: int
    sequence: int
    start_ms: int
    end_ms: int
    visual_description: str
    action_description: str
    narration: str
    subtitle_draft: str


class ProductVideoSourceRead(BaseModel):
    variant_id: int
    script_version_id: int
    platform: str
    language: str
    content_digest: str
    full_narration: str
    narration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenes: list[ProductVideoSceneRead]


class JobSubmitRead(BaseModel):
    job: ExecutionJobRead
    reused: bool


class ProductAssetUploadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    file_name: str
    file_type: str
    content_type: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    created_at: datetime
    reused: bool = False


class ProductVideoSelection(BaseModel):
    variant_id: int
    script_version_id: int

    @model_validator(mode="after")
    def validate_ids(self) -> "ProductVideoSelection":
        if self.variant_id <= 0 or self.script_version_id <= 0:
            raise ValueError("Exact positive identities are required")
        return self


class ThreePlatformVideoPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_product_asset_id: int = Field(gt=0)
    reference_product_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selections: list[ProductVideoSelection] = Field(min_length=3, max_length=3)


class PlatformVideoProductionEstimate(BaseModel):
    platform: str = Field(pattern=r"^(tiktok|youtube|instagram)$")
    variant_id: int
    script_version_id: int
    scene_count: int
    wanx_image_generation_calls: int
    happyhorse_generation_calls: int = 0
    dynamic_video_generation_calls: int = 1
    qwen_tts_generation_calls: int = 1
    known_estimated_cost: Decimal
    currency: str = "CNY"


class ThreePlatformVideoPreflightRead(ThreePlatformVideoPreflightRequest):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    platforms: list[PlatformVideoProductionEstimate]
    wanx_image_generation_calls: int
    happyhorse_generation_calls: int
    dynamic_video_generation_calls: int
    dynamic_video_provider: Literal["happyhorse", "wanx_i2v"]
    dynamic_video_model: str
    qwen_tts_generation_calls: int
    qwen_script_generation_calls: int = 0
    known_estimated_cost: Decimal
    currency: str = "CNY"
    cost_estimate_complete: bool = False
    unpriced_cost_components: list[str] = Field(default_factory=lambda: ["qwen_tts"])
    requires_cost_confirmation: bool = True
    ready: bool
    missing_requirements: list[str]
    provider_call_count: int = 0
    database_writes: int = 0


class ProductVideoProductionCreateRequest(ThreePlatformVideoPreflightRequest):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(
        min_length=8, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$"
    )
    cost_confirmed: Literal[True]


class ProductVideoProductionResumeRequest(BaseModel):
    confirm_uncertain_voiceover_replacement: Literal[True] | None = None


class ProductVideoProductionBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    reference_product_asset_id: int
    reference_product_asset_sha256: str
    input_digest: str
    idempotency_key: str
    status: str
    known_estimated_cost: Decimal
    currency: str
    cost_estimate_complete: bool
    cost_confirmed: bool
    provider_call_budget: int
    safe_error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ProductVideoProductionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    production_batch_id: int
    batch_video_variant_id: int
    script_version_id: int
    platform: str
    status: str
    stage: str
    stage_state_json: dict[str, object]
    video_project_id: int | None
    cloud_render_task_id: int | None
    cloud_render_artifact_id: int | None
    composition_id: int | None
    voiceover_artifact_id: int | None
    enhancement_id: int | None
    final_video_artifact_id: int | None
    subtitle_artifact_id: int | None
    safe_error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ProductVideoProductionCreateRead(BaseModel):
    batch: ProductVideoProductionBatchRead
    items: list[ProductVideoProductionItemRead]
    reused: bool
