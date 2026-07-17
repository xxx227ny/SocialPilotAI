from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator


class CampaignRowSchema(BaseModel):
    platform: str = Field(min_length=1)
    campaign_name: str = Field(min_length=1)
    date: date
    impressions: int = Field(ge=0)
    clicks: int = Field(ge=0)
    conversions: int = Field(ge=0)
    spend: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    revenue: Decimal = Field(ge=0, max_digits=14, decimal_places=2)

    @field_validator("platform", "campaign_name")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("campaign text fields cannot be empty")
        return cleaned

    @model_validator(mode="after")
    def validate_funnel_counts(self) -> "CampaignRowSchema":
        if self.clicks > self.impressions:
            raise ValueError("clicks cannot exceed impressions")
        if self.conversions > self.clicks:
            raise ValueError("conversions cannot exceed clicks")
        return self


class CampaignUploadResponse(BaseModel):
    product_id: int
    imported_count: int


class CampaignMetricsSchema(BaseModel):
    impressions: int
    clicks: int
    conversions: int
    spend: float
    revenue: float
    ctr: float
    conversion_rate: float
    cpa: float | None
    roas: float | None
