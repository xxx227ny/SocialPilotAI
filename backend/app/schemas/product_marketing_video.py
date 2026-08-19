from datetime import datetime

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
