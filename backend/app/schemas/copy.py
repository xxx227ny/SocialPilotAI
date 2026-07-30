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

PlatformName = Literal["TikTok", "Instagram", "Facebook"]
REQUIRED_PLATFORMS = {"TikTok", "Instagram", "Facebook"}
V2_COPY_CONTRACT_VERSION = "v2-copy-v1"


class PlatformCopySchema(BaseModel):
    platform: PlatformName
    hook: str = Field(min_length=1)
    caption: str = Field(min_length=1)
    hashtags: list[str] = Field(min_length=1)
    cta: str = Field(min_length=1)

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().casefold()
        canonical = {
            "tiktok": "TikTok",
            "instagram": "Instagram",
            "facebook": "Facebook",
        }.get(normalized)
        return canonical if canonical is not None else value.strip()

    @field_validator("hook", "caption", "cta")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("copy text fields cannot be empty")
        return cleaned

    @field_validator("hashtags")
    @classmethod
    def validate_hashtags(cls, value: list[str]) -> list[str]:
        cleaned = [hashtag.strip() for hashtag in value]
        if any(not hashtag for hashtag in cleaned):
            raise ValueError("hashtags cannot contain empty values")
        return cleaned


class CopyMatrixSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int = Field(gt=0)
    copies: list[PlatformCopySchema] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_platform_matrix(self) -> "CopyMatrixSchema":
        platforms = [copy.platform for copy in self.copies]
        if len(set(platforms)) != 3 or set(platforms) != REQUIRED_PLATFORMS:
            raise ValueError(
                "copies must contain TikTok, Instagram and Facebook exactly once"
            )
        return self


class TaskBoundCopyMatrixSchema(BaseModel):
    """Strict variable-platform output for an exact MarketingBrief snapshot."""

    model_config = ConfigDict(from_attributes=True)

    product_id: int = Field(gt=0)
    copies: list[PlatformCopySchema] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_requested_platforms(
        self, info: ValidationInfo
    ) -> "TaskBoundCopyMatrixSchema":
        platforms = [copy.platform for copy in self.copies]
        if len(platforms) != len(set(platforms)):
            raise ValueError("copies cannot contain duplicate platforms")

        requested = (
            info.context.get("requested_platforms")
            if info.context is not None
            else None
        )
        if requested is not None and (
            len(platforms) != len(requested) or set(platforms) != set(requested)
        ):
            raise ValueError(
                "copies must contain exactly the requested MarketingBrief platforms"
            )
        return self


class CopyMatrixRead(TaskBoundCopyMatrixSchema):
    id: int
    marketing_strategy_id: int
    created_at: datetime


class CopyMatrixExecutionRead(BaseModel):
    source_task_id: int
    source_strategy_id: int
    source_product_id: int
    source_kind: Literal["marketing_brief_and_strategy"] = (
        "marketing_brief_and_strategy"
    )
    requested_platforms: list[PlatformName]
    copy_matrix: CopyMatrixRead
    strategy_association_persisted: bool = True
    brief_association_persisted: bool = False
    association_notice: str


class CopyPreflightProductSummary(BaseModel):
    id: int
    name: str
    category: str
    description: str
    selling_points: list[str]


class CopyPreflightStrategySummary(BaseModel):
    id: int
    positioning: str
    audience_insights_count: int
    angles_count: int
    risks_count: int
    evidence_count: int


class CopyPreflightRead(BaseModel):
    task_id: int
    strategy_id: int
    product_id: int
    ready: bool
    input_ready: bool
    provider_configured: bool
    execution_enabled: bool
    contract_ready: bool
    ready_for_execution: bool
    missing_requirements: list[str]
    platforms: list[str]
    product_summary: CopyPreflightProductSummary
    strategy_summary: CopyPreflightStrategySummary
    association_persisted: bool = False
    association_notice: str
    preflight_only: bool = True
    execution_will_call_ai: bool = True
    execution_will_create_copy_matrix: bool = True
    cost_notice: str


class StrictV2CopyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class V2CopySourceRequest(StrictV2CopyModel):
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_marketing_strategy_id: int = Field(gt=0)
    source_copy_matrix_id: int = Field(gt=0)
    source_video_project_id: int = Field(gt=0)
    recommendation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    recommendation: GrowthRecommendationConstraints


class V2CopyExecutionRequest(V2CopySourceRequest):
    expected_preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class V2PlatformCopySchema(StrictV2CopyModel):
    platform: PlatformName
    hook: str = Field(min_length=1, max_length=240)
    caption: str = Field(min_length=1, max_length=1200)
    hashtags: list[str] = Field(min_length=1, max_length=12)
    cta: str = Field(min_length=1, max_length=240)

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        canonical = {
            "tiktok": "TikTok",
            "instagram": "Instagram",
            "facebook": "Facebook",
        }.get(value.strip().casefold())
        return canonical if canonical is not None else value.strip()

    @field_validator("hashtags")
    @classmethod
    def validate_hashtags(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > 80 for item in cleaned):
            raise ValueError("hashtags must be non-empty and at most 80 characters")
        if len({item.casefold() for item in cleaned}) != len(cleaned):
            raise ValueError("hashtags must be unique")
        return cleaned


class V2CopyProviderOutput(StrictV2CopyModel):
    copies: list[V2PlatformCopySchema] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_platform_order(
        self, info: ValidationInfo
    ) -> "V2CopyProviderOutput":
        platforms = [copy.platform for copy in self.copies]
        if len(platforms) != len(set(platforms)):
            raise ValueError("V2 Copy platforms must be unique")
        expected = (
            info.context.get("target_platforms")
            if info.context is not None
            else None
        )
        if expected is not None and platforms != list(expected):
            raise ValueError(
                "V2 Copy platforms must exactly match the required order"
            )
        return self


class V2CopyPreflightRead(StrictV2CopyModel):
    product_id: int
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_recommendation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_marketing_strategy_id: int
    source_copy_matrix_id: int
    source_video_project_id: int
    target_platforms: list[PlatformName] = Field(min_length=1, max_length=3)
    expected_copy_count: int = Field(ge=1, le=3)
    input_ready: bool
    provider_configured: bool
    copy_execution_enabled: bool
    v2_copy_execution_enabled: bool
    contract_ready: bool
    ready_for_execution: bool
    missing_requirements: list[str]
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_only: Literal[True] = True
    execution_will_call_ai: Literal[True] = True
    execution_will_create_copy_matrix: Literal[True] = True
    execution_will_create_video_project: Literal[False] = False
    execution_will_modify_source: Literal[False] = False
    parent_relation_will_be_persisted: Literal[False] = False
    automatic_action_allowed: Literal[False] = False
    cost_notice: str
    association_notice: str


class V2CopyExecutionRead(StrictV2CopyModel):
    version: Literal["v2-copy-candidate-v1"] = "v2-copy-candidate-v1"
    product_id: int
    source_context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_recommendation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_marketing_strategy_id: int
    source_copy_matrix_id: int
    source_video_project_id: int
    target_platforms: list[PlatformName]
    generated_copy_matrix: CopyMatrixRead
    source_kind: Literal["feedback_recommendation_constraints"] = (
        "feedback_recommendation_constraints"
    )
    generation_scope: Literal["copy_only"] = "copy_only"
    copy_generation_triggered: Literal[True] = True
    video_generation_triggered: Literal[False] = False
    provider_calls: Literal[1] = 1
    source_copy_modified: Literal[False] = False
    recommendation_persisted: Literal[False] = False
    parent_relation_persisted: Literal[False] = False
    version_label_persisted: Literal[False] = False
    automatic_action_allowed: Literal[False] = False
    association_notice: str
