from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PlatformName = Literal["TikTok", "Instagram", "Facebook"]
REQUIRED_PLATFORMS = {"TikTok", "Instagram", "Facebook"}


class PlatformCopySchema(BaseModel):
    platform: PlatformName
    hook: str = Field(min_length=1)
    caption: str = Field(min_length=1)
    hashtags: list[str] = Field(min_length=1)
    cta: str = Field(min_length=1)

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
