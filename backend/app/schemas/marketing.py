from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.product import clean_required_text

SUPPORTED_MARKETING_PLATFORMS = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "pinterest": "Pinterest",
}


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
        cleaned: list[str] = []
        seen: set[str] = set()
        for platform in value:
            normalized = platform.strip().casefold()
            if not normalized:
                raise ValueError("platforms cannot contain empty values")
            canonical = SUPPORTED_MARKETING_PLATFORMS.get(normalized)
            if canonical is None:
                raise ValueError("platform is not supported")
            if normalized not in seen:
                cleaned.append(canonical)
                seen.add(normalized)
        if len(cleaned) > 4:
            raise ValueError("platforms cannot contain more than 4 values")
        return cleaned


class MarketingTaskRead(MarketingTaskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_markets: list[str]
    created_at: datetime
