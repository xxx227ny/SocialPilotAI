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
