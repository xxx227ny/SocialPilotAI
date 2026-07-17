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
