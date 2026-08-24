from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Platform = Literal["youtube", "tiktok", "instagram"]


class BatchVideoRequest(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=20)
    platforms: list[Platform] = Field(min_length=1, max_length=3)
    variants_per_platform: int = Field(ge=1, le=10)
    duration_seconds: Literal[15] = 15
    aspect_ratio: Literal["9:16"] = "9:16"
    language: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$", max_length=35)
    priority: int = Field(default=50, ge=0, le=100)
    max_concurrency: int = Field(default=3, ge=1, le=20)
    creative_angle: str | None = Field(default=None, max_length=300)
    idempotency_key: str = Field(
        min_length=8, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$"
    )

    @field_validator("creative_angle")
    @classmethod
    def clean_angle(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class BatchVideoVariantPlan(BaseModel):
    product_id: int
    platform: Platform
    variant_index: int
    brand_kit_version_id: int | None
    brand_kit_version_digest: str | None
    source_digest: str


class BatchVideoPreflightRead(BaseModel):
    ready: bool
    contract_version: str
    request_digest: str
    preflight_digest: str
    expires_at: datetime
    variant_count: int
    max_concurrency: int
    variants: list[BatchVideoVariantPlan]
    current_stage_cost: Decimal
    currency: str
    cost_scope: Literal["orchestration_only"]
    downstream_provider_cost_status: Literal["NOT_ESTIMATED"]
    provider_call_count: Literal[0]
    ffmpeg_call_count: Literal[0]


class BatchVideoCreateRequest(BatchVideoRequest):
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    cost_confirmed: Literal[True]


class BatchVideoVariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_video_job_id: int
    product_id: int
    platform: str
    variant_index: int
    duration_seconds: int
    aspect_ratio: str
    language: str
    creative_angle: str | None
    brand_kit_version_id: int | None
    brand_kit_version_digest: str | None
    source_digest: str
    idempotency_key: str
    execution_job_id: int
    status: str
    result_entity_type: str | None
    result_entity_id: int | None
    safe_error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class BatchVideoJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_digest: str
    idempotency_key: str
    status: str
    priority: int
    variant_count: int
    max_concurrency: int
    current_stage_cost: Decimal
    currency: str
    cost_scope: str
    downstream_provider_cost_status: str
    cost_confirmed: bool
    qwen_script_call_quota: int
    qwen_script_calls_reserved: int
    frozen_constraints_json: dict[str, object]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class BatchVideoCreateRead(BaseModel):
    batch: BatchVideoJobRead
    variants: list[BatchVideoVariantRead]
    reused: bool
