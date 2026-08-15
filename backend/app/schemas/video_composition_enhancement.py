from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.execution import ExecutionJobRead


class SubtitleCueInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=1)
    start_ms: int = Field(ge=0, lt=15000)
    end_ms: int = Field(gt=0, le=15000)
    text: str = Field(min_length=1, max_length=240)

    @field_validator("text")
    @classmethod
    def safe_text(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or "\ufffd" in normalized
            or "-->" in normalized
            or "WEBVTT" in normalized.upper()
            or any(
                ord(character) < 32 and character not in "\n\t"
                for character in normalized
            )
        ):
            raise ValueError("subtitle text is unsafe")
        return normalized


class SubtitleStyleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    font_size: int = Field(default=48, ge=32, le=72)
    max_chars_per_line: int = Field(default=18, ge=8, le=32)
    bottom_margin: int = Field(default=280, ge=220, le=520)
    outline_width: int = Field(default=3, ge=1, le=6)


class EnhancementMixInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voiceover_gain_db: float = Field(default=0, ge=-12, le=12, allow_inf_nan=False)
    music_gain_db: float = Field(default=-18, ge=-36, le=0, allow_inf_nan=False)
    ducking_reduction_db: float = Field(default=12, ge=0, le=24, allow_inf_nan=False)
    target_lufs: float = Field(default=-14, ge=-24, le=-9, allow_inf_nan=False)
    true_peak_db: float = Field(default=-1, ge=-6, le=-0.1, allow_inf_nan=False)


class VideoCompositionEnhancementPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    composition_id: int = Field(gt=0)
    source_artifact_id: int = Field(gt=0)
    voiceover_artifact_id: int = Field(gt=0)
    music_artifact_id: int | None = Field(default=None, gt=0)
    cues: list[SubtitleCueInput] = Field(min_length=1, max_length=120)
    style: SubtitleStyleInput = Field(default_factory=SubtitleStyleInput)
    mix: EnhancementMixInput = Field(default_factory=EnhancementMixInput)

    @model_validator(mode="after")
    def validate_cues(self) -> VideoCompositionEnhancementPreflightRequest:
        ordered = sorted(self.cues, key=lambda cue: cue.sequence)
        if [cue.sequence for cue in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("subtitle sequence must be continuous from 1")
        previous_end = 0
        for cue in ordered:
            if cue.end_ms <= cue.start_ms or cue.start_ms < previous_end:
                raise ValueError("subtitle cues must be ordered without overlap")
            previous_end = cue.end_ms
        return self


class FrozenAudioArtifactRead(BaseModel):
    id: int
    kind: Literal["voiceover", "music"]
    product_id: int
    video_project_id: int
    composition_id: int
    content_type: str
    size_bytes: int
    sha256: str
    duration_ms: int


class FrozenEnhancementParametersRead(BaseModel):
    voiceover_gain_millidb: int
    music_gain_millidb: int
    ducking_reduction_millidb: int
    target_lufs_milli: int
    true_peak_millidb: int


class VideoCompositionEnhancementPreflightRead(BaseModel):
    product_id: int
    video_project_id: int
    composition_id: int
    source_artifact_id: int
    voiceover_artifact_id: int
    music_artifact_id: int | None
    source_artifact_sha256: str
    voiceover: FrozenAudioArtifactRead
    music: FrozenAudioArtifactRead | None
    cues: list[SubtitleCueInput]
    style: SubtitleStyleInput
    mix: EnhancementMixInput
    parameters: FrozenEnhancementParametersRead
    input_digest: str
    source_chain_digest: str
    preflight_digest: str
    expires_at: datetime
    ready: bool
    missing_requirements: list[str]
    execution_notice: str


class VideoCompositionEnhancementSubmitRequest(
    VideoCompositionEnhancementPreflightRequest
):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_chain_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    local_cpu_cost_confirmed: Literal[True]


class VideoCompositionAudioArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    video_project_id: int
    composition_id: int
    kind: str
    content_type: str
    size_bytes: int
    sha256: str
    duration_ms: int
    created_at: datetime


class VideoCompositionSubtitleArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    enhancement_id: int
    content_type: str
    size_bytes: int
    sha256: str
    format: str
    cue_count: int
    created_at: datetime


class VideoCompositionEnhancementArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    enhancement_id: int
    subtitle_artifact_id: int
    content_type: str
    size_bytes: int
    sha256: str
    duration_ms: int
    width: int
    height: int
    fps_numerator: int
    fps_denominator: int
    video_codec: str
    video_profile: str
    pixel_format: str
    audio_codec: str
    audio_profile: str
    audio_sample_rate: int
    audio_channels: int
    container: str
    measured_lufs_milli: int
    measured_true_peak_millidb: int
    audio_video_sync_offset_ms: int
    longest_black_segment_ms: int
    subtitle_format: str
    subtitle_cue_count: int
    subtitle_sha256: str
    source_chain_digest: str
    created_at: datetime


class VideoCompositionEnhancementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    video_project_id: int
    composition_id: int
    source_artifact_id: int
    voiceover_artifact_id: int
    music_artifact_id: int | None
    input_digest: str
    source_chain_digest: str
    status: str
    safe_error_code: str | None
    subtitle_artifact: VideoCompositionSubtitleArtifactRead | None
    artifact: VideoCompositionEnhancementArtifactRead | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class VideoCompositionEnhancementSubmitRead(BaseModel):
    enhancement: VideoCompositionEnhancementRead
    job: ExecutionJobRead
    reused: bool
