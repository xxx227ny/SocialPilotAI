from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.campaign import CampaignMetricsSchema


class GrowthRecommendation(BaseModel):
    problems: list[str] = Field(min_length=1)
    recommendations: list[str] = Field(min_length=1)
    budget_suggestion: str = Field(min_length=1)
    creative_suggestions: list[str] = Field(min_length=1)

    @field_validator("budget_suggestion")
    @classmethod
    def validate_budget_suggestion(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("budget_suggestion cannot be empty")
        return cleaned

    @field_validator("problems", "recommendations", "creative_suggestions")
    @classmethod
    def validate_non_empty_lists(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("growth recommendation lists cannot contain empty values")
        return cleaned


class GrowthAnalysisResponse(BaseModel):
    metrics: CampaignMetricsSchema
    recommendation: GrowthRecommendation


class FeedbackPlatformMetrics(BaseModel):
    platform: str
    metrics: CampaignMetricsSchema


class FeedbackContextRead(BaseModel):
    version: Literal["v1"] = "v1"
    product_id: int
    data_source: Literal["stored_campaigns"] = "stored_campaigns"
    context_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    feedback_only: Literal[True] = True
    recommendation_generated: Literal[False] = False
    generation_triggered: Literal[False] = False
    provider_calls: Literal[0] = 0

    campaign_ids: list[int]
    campaign_count: int = Field(ge=0)
    date_from: date | None
    date_to: date | None
    platforms: list[str]
    overall_metrics: CampaignMetricsSchema | None
    platform_metrics: list[FeedbackPlatformMetrics]

    marketing_strategy_id: int | None
    copy_matrix_id: int | None
    video_project_id: int | None
    content_chain_ready: bool
    content_chain_selection: Literal["latest_video_project_exact_chain"] = (
        "latest_video_project_exact_chain"
    )

    campaign_association_scope: Literal["product_only"] = "product_only"
    creative_attribution_persisted: Literal[False] = False
    marketing_brief_attribution_persisted: Literal[False] = False
    association_notice: str

    context_ready: bool
    metrics_ready: bool
    missing_requirements: list[str]
