from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.execution import ExecutionJobRead


class CompositionShotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=1)
    start_ms: int = Field(ge=0, lt=15000)
    end_ms: int = Field(gt=0, le=15000)
    trim_start_ms: int = Field(default=0, ge=0)
    trim_end_ms: int = Field(gt=0)
    transition_type: Literal["cut"] = "cut"
    render_task_id: int = Field(gt=0)
    artifact_id: int = Field(gt=0)


class VideoCompositionPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_project_id: int = Field(gt=0)
    shots: list[CompositionShotInput] = Field(min_length=3, max_length=100)

    @model_validator(mode="after")
    def validate_timeline(self) -> VideoCompositionPreflightRequest:
        ordered = sorted(self.shots, key=lambda shot: shot.sequence)
        if [shot.sequence for shot in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("shot sequence must be continuous from 1")
        cursor = 0
        for shot in ordered:
            if shot.start_ms != cursor or shot.end_ms <= shot.start_ms:
                raise ValueError(
                    "shot timeline must be continuous without gaps or overlap"
                )
            if shot.trim_end_ms - shot.trim_start_ms < shot.end_ms - shot.start_ms:
                raise ValueError("shot trim duration cannot cover timeline duration")
            cursor = shot.end_ms
        if cursor != 15000:
            raise ValueError("shot timeline must end at 15000ms")
        return self


class FrozenCompositionShotRead(CompositionShotInput):
    product_id: int
    video_project_id: int
    artifact_sha256: str


class VideoCompositionPreflightRead(BaseModel):
    product_id: int
    video_project_id: int
    shots: list[FrozenCompositionShotRead]
    input_digest: str
    source_chain_digest: str
    preflight_digest: str
    expires_at: datetime
    ready: bool
    missing_requirements: list[str]
    output_contract: dict[str, object]
    execution_notice: str
    placeholder_audio_notice: str


class VideoCompositionSubmitRequest(VideoCompositionPreflightRequest):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_chain_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    local_cpu_cost_confirmed: Literal[True]


class VideoCompositionShotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sequence: int
    start_ms: int
    end_ms: int
    trim_start_ms: int
    trim_end_ms: int
    transition_type: str
    product_id: int
    video_project_id: int
    source_render_task_id: int
    source_artifact_id: int
    source_artifact_sha256: str


class VideoCompositionArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    composition_id: int
    content_type: str
    size_bytes: int
    sha256: str
    duration_ms: int
    width: int
    height: int
    fps_numerator: int
    fps_denominator: int
    video_codec: str
    pixel_format: str
    audio_codec: str
    audio_sample_rate: int
    container: str
    source_chain_digest: str
    created_at: datetime


class VideoCompositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    video_project_id: int
    input_digest: str
    source_chain_digest: str
    version_number: int
    duration_ms: int
    aspect_ratio: str
    width: int
    height: int
    fps_numerator: int
    fps_denominator: int
    status: str
    safe_error_code: str | None
    shots: list[VideoCompositionShotRead]
    artifact: VideoCompositionArtifactRead | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class VideoCompositionSubmitRead(BaseModel):
    composition: VideoCompositionRead
    job: ExecutionJobRead
    reused: bool
