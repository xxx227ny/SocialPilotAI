from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.product import clean_required_text


class MarketingTaskCreate(BaseModel):
    product_id: int
    audience: str
    language: str
    platforms: list[str] = Field(min_length=1)
    tone: str
    objective: str

    @field_validator("audience", "language", "tone", "objective")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return clean_required_text(value, "marketing task field")

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, value: list[str]) -> list[str]:
        cleaned = [platform.strip() for platform in value]
        if any(not platform for platform in cleaned):
            raise ValueError("platforms cannot contain empty values")
        normalized = [platform.casefold() for platform in cleaned]
        if len(normalized) != len(set(normalized)):
            raise ValueError("platforms cannot contain duplicates")
        return cleaned


class MarketingTaskRead(MarketingTaskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
