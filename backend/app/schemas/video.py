from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.schemas.growth import GrowthRecommendationConstraints

V2_VIDEO_PROJECT_CONTRACT_VERSION = "v2-video-project-v1"
INITIAL_VIDEO_PROJECT_CONTRACT_VERSION = "initial-video-project-v1"


class VideoProjectRequest(BaseModel):
    platform: str = Field(default="TikTok", min_length=1, max_length=100)
    duration_seconds: int = Field(default=30, gt=0, le=180)
    aspect_ratio: str = Field(default="9:16", min_length=1, max_length=20)

    @field_validator("platform", "aspect_ratio")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("video request fields cannot be empty")
        return cleaned


class VideoSceneSchema(BaseModel):
    sequence: int = Field(gt=0)
    duration_seconds: int = Field(gt=0)
    shot_type: str = Field(min_length=1)
    visual_description: str = Field(min_length=1)
    action: str = Field(min_length=1)
    narration: str = Field(min_length=1)

    @field_validator("shot_type", "visual_description", "action", "narration")
    @classmethod
    def clean_scene_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("scene text fields cannot be empty")
        return cleaned


class VideoPlanSchema(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    concept: str = Field(min_length=1)
    platform: str = Field(min_length=1, max_length=100)
    duration_seconds: int = Field(gt=0, le=180)
    aspect_ratio: str = Field(min_length=1, max_length=20)
    scenes: list[VideoSceneSchema] = Field(min_length=1)
    cta: str = Field(min_length=1)

    @field_validator("title", "concept", "platform", "aspect_ratio", "cta")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("video plan fields cannot be empty")
        return cleaned

    @model_validator(mode="after")
    def validate_scene_timeline(self) -> "VideoPlanSchema":
        sequences = [scene.sequence for scene in self.scenes]
        if len(sequences) != len(set(sequences)):
            raise ValueError("scene sequences cannot contain duplicates")
        scene_duration = sum(scene.duration_seconds for scene in self.scenes)
        if scene_duration != self.duration_seconds:
            raise ValueError("scene durations must equal duration_seconds")
        return self


class VideoProjectSchema(VideoPlanSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    marketing_strategy_id: int
    copy_matrix_id: int | None
    status: str
    created_at: datetime
    updated_at: datetime


class StrictInitialVideoModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InitialVideoProjectSourceRequest(StrictInitialVideoModel):
    strategy_id: int = Field(gt=0)
    copy_matrix_id: int = Field(gt=0)
    platform: Literal["TikTok", "Instagram", "Facebook"]
    duration_seconds: Literal[15, 30]
    aspect_ratio: Literal["9:16"] = "9:16"


class InitialVideoProjectSourceRead(StrictInitialVideoModel):
    product_id: int
    strategy_id: int
    copy_matrix_id: int
    selected_by: Literal["latest_valid_copy_matrix"] = "latest_valid_copy_matrix"
    provider_calls: Literal[0] = 0
    database_writes: Literal[0] = 0


class InitialVideoProjectExecutionRequest(InitialVideoProjectSourceRequest):
    product_id: int = Field(gt=0)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    cost_confirmed: Literal[True]

    @field_validator("preflight_expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("preflight_expires_at must include a timezone")
        return value


class InitialVideoProjectPreflightRead(StrictInitialVideoModel):
    product_id: int
    strategy_id: int
    copy_matrix_id: int
    platform: Literal["TikTok", "Instagram", "Facebook"]
    duration_seconds: Literal[15, 30]
    aspect_ratio: Literal["9:16"]
    input_ready: bool
    provider_configured: bool
    execution_enabled: bool
    contract_ready: bool
    ready_for_execution: bool
    missing_requirements: list[str]
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime
    preflight_only: Literal[True] = True
    provider_calls: Literal[0] = 0
    database_writes: Literal[0] = 0
    execution_will_call_qwen: Literal[True] = True
    execution_will_call_wanx: Literal[False] = False
    execution_will_create_video_project: Literal[True] = True
    automatic_action_allowed: Literal[False] = False
    cost_notice: str
    association_notice: str


class InitialVideoProjectExecutionRead(StrictInitialVideoModel):
    version: Literal["initial-video-project-v1"] = "initial-video-project-v1"
    product_id: int
    strategy_id: int
    copy_matrix_id: int
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_video_project: VideoProjectSchema
    reused: bool
    provider_calls: Literal[0, 1]
    wanx_calls: Literal[0] = 0
    render_tasks_created: Literal[0] = 0
    artifacts_created: Literal[0] = 0
    automatic_action_allowed: Literal[False] = False
    association_notice: str


class StrictV2VideoModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class V2VideoProjectSourceRequest(StrictV2VideoModel):
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_marketing_strategy_id: int = Field(gt=0)
    source_copy_matrix_id: int = Field(gt=0)
    source_video_project_id: int = Field(gt=0)
    recommendation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    recommendation: GrowthRecommendationConstraints
    candidate_copy_matrix_id: int = Field(gt=0)


class V2VideoProjectExecutionRequest(V2VideoProjectSourceRequest):
    expected_preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class V2VideoSceneProviderOutput(StrictV2VideoModel):
    sequence: int = Field(gt=0)
    duration_seconds: int = Field(gt=0, le=180)
    shot_type: str = Field(min_length=1, max_length=120)
    visual_description: str = Field(min_length=1, max_length=1000)
    action: str = Field(min_length=1, max_length=600)
    narration: str = Field(min_length=1, max_length=1000)


class V2VideoProjectProviderOutput(StrictV2VideoModel):
    title: str = Field(min_length=1, max_length=300)
    concept: str = Field(min_length=1, max_length=1600)
    scenes: list[V2VideoSceneProviderOutput] = Field(min_length=1, max_length=12)
    cta: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def validate_timeline(self, info: ValidationInfo) -> "V2VideoProjectProviderOutput":
        sequences = [scene.sequence for scene in self.scenes]
        if sequences != list(range(1, len(self.scenes) + 1)):
            raise ValueError(
                "scene sequences must start at 1 and be ordered and continuous"
            )
        expected_duration = (
            info.context.get("duration_seconds") if info.context is not None else None
        )
        if expected_duration is not None and sum(
            scene.duration_seconds for scene in self.scenes
        ) != int(expected_duration):
            raise ValueError(
                "scene durations must equal the source VideoProject duration"
            )
        return self


class V2VideoProjectPreflightRead(StrictV2VideoModel):
    product_id: int
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_recommendation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_marketing_strategy_id: int
    source_copy_matrix_id: int
    source_video_project_id: int
    candidate_copy_matrix_id: int
    platform: str
    duration_seconds: int
    aspect_ratio: str
    input_ready: bool
    provider_configured: bool
    v2_video_project_execution_enabled: bool
    contract_ready: bool
    ready_for_execution: bool
    missing_requirements: list[str]
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_only: Literal[True] = True
    execution_will_call_qwen: Literal[True] = True
    execution_will_create_video_project: Literal[True] = True
    execution_will_call_wanx: Literal[False] = False
    execution_will_create_render_task: Literal[False] = False
    execution_will_create_artifact: Literal[False] = False
    automatic_action_allowed: Literal[False] = False
    cost_notice: str
    association_notice: str


class V2VideoProjectExecutionRead(StrictV2VideoModel):
    version: Literal["v2-video-project-candidate-v1"] = "v2-video-project-candidate-v1"
    product_id: int
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_recommendation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_marketing_strategy_id: int
    source_copy_matrix_id: int
    source_video_project_id: int
    candidate_copy_matrix_id: int
    generated_video_project: VideoProjectSchema
    provider_calls: Literal[1] = 1
    wanx_calls: Literal[0] = 0
    render_tasks_created: Literal[0] = 0
    artifacts_created: Literal[0] = 0
    source_video_project_modified: Literal[False] = False
    source_copy_modified: Literal[False] = False
    candidate_copy_modified: Literal[False] = False
    recommendation_persisted: Literal[False] = False
    candidate_copy_matrix_association_persisted: Literal[True] = True
    candidate_copy_source_parent_relation_persisted: Literal[False] = False
    source_video_parent_relation_persisted: Literal[False] = False
    rendered: Literal[False] = False
    automatic_action_allowed: Literal[False] = False
    association_notice: str
