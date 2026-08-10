from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarketingStrategySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    positioning: str = Field(min_length=1)
    audience_insights: list[str] = Field(min_length=1)
    angles: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)

    @field_validator("positioning")
    @classmethod
    def validate_positioning(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("positioning cannot be empty")
        return cleaned

    @field_validator("audience_insights", "angles", "risks", "evidence")
    @classmethod
    def validate_non_empty_list(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("strategy lists cannot contain empty values")
        return cleaned


class MarketingStrategyRead(MarketingStrategySchema):
    id: int
    product_id: int
    created_at: datetime


class MarketingStrategyExecutionRead(BaseModel):
    source_task_id: int
    source_product_id: int
    source_kind: Literal["marketing_brief"] = "marketing_brief"
    strategy: MarketingStrategyRead
    association_persisted: bool = False
    association_notice: str


class StrategyPreflightProductSummary(BaseModel):
    id: int
    name: str
    category: str
    description: str
    selling_points: list[str]


class StrategyPreflightRead(BaseModel):
    task_id: int
    product_id: int
    ready: bool
    input_ready: bool
    ready_for_execution: bool
    missing_requirements: list[str]
    product_summary: StrategyPreflightProductSummary
    target_market_snapshot: list[str]
    platforms: list[str]
    audience: str
    language: str
    tone: str
    objective: str
    provider_label: str
    model_label: str
    provider_configured: bool
    execution_enabled: bool
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime
    preflight_only: bool = True
    execution_will_call_ai: bool = True
    execution_will_create_strategy: bool = True
    cost_notice: str


class StrategyJobEnqueueRequest(BaseModel):
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
