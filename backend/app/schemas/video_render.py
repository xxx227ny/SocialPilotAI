from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class VideoRenderOperationRead(BaseModel):
    video_project_id: int
    product_id: int
    marketing_strategy_id: int
    copy_matrix_id: int
    task: VideoRenderTaskSafeRead
    artifact: VideoRenderArtifactReferenceRead | None = None
    reused: bool
    external_call: bool
    recovered: bool = False
    association_notice: str


class VideoRenderPreflightRead(BaseModel):
    video_project_id: int
    product_id: int
    marketing_strategy_id: int
    copy_matrix_id: int
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
    preflight_only: Literal[True] = True
    estimated_cost_notice: str
    association_notice: str


class LiveVideoRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_live_generation: Literal[True]
