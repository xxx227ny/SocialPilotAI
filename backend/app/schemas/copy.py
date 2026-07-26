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

PlatformName = Literal["TikTok", "Instagram", "Facebook"]
REQUIRED_PLATFORMS = {"TikTok", "Instagram", "Facebook"}


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
