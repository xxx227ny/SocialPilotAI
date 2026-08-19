from datetime import datetime
from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SUPPORTED_ASSET_TYPES = {"jpg", "jpeg", "png", "webp"}


def clean_required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    return cleaned


class ProductBase(BaseModel):
    name: str
    category: str | None = None
    description: str | None = None
    selling_points: list[str] = Field(min_length=1)
    target_markets: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return clean_required_text(value, "name")

    @field_validator("selling_points")
    @classmethod
    def validate_selling_points(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("selling_points cannot contain empty values")
        return cleaned

    @field_validator("target_markets")
    @classmethod
    def clean_target_markets(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


ProductName = Annotated[str, StringConstraints(min_length=2, max_length=120)]
ProductCategory = Annotated[str, StringConstraints(min_length=2, max_length=80)]
ProductDescription = Annotated[str, StringConstraints(min_length=10, max_length=2000)]
SellingPoint = Annotated[str, StringConstraints(min_length=2, max_length=160)]


class ProductCreate(BaseModel):
    name: ProductName
    category: ProductCategory
    description: ProductDescription
    selling_points: list[SellingPoint] = Field(min_length=1, max_length=8)
    target_markets: list[str] = Field(default_factory=list)

    @field_validator("name", "category", "description", mode="before")
    @classmethod
    def trim_create_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("selling_points", mode="before")
    @classmethod
    def clean_create_selling_points(cls, value: object) -> object:
        if not isinstance(value, list):
            return value

        cleaned: list[object] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                cleaned.append(item)
                continue
            normalized = item.strip()
            if not normalized:
                raise ValueError("selling_points cannot contain empty values")
            if normalized not in seen:
                cleaned.append(normalized)
                seen.add(normalized)
        return cleaned

    @field_validator("target_markets")
    @classmethod
    def clean_create_target_markets(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class ProductUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    selling_points: list[str] | None = Field(default=None, min_length=1)
    target_markets: list[str] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return clean_required_text(value, "name") if value is not None else value

    @field_validator("selling_points")
    @classmethod
    def validate_selling_points(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("selling_points cannot contain empty values")
        return cleaned

    @field_validator("target_markets")
    @classmethod
    def clean_target_markets(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return [item.strip() for item in value if item.strip()]


class ProductAssetCreate(BaseModel):
    file_name: str
    file_path: str
    file_type: str

    @field_validator("file_name", "file_path")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return clean_required_text(value, "file value")

    @field_validator("file_type")
    @classmethod
    def validate_file_type(cls, value: str) -> str:
        normalized = value.lower().strip().removeprefix(".")
        if normalized not in SUPPORTED_ASSET_TYPES:
            raise ValueError("Only jpg, jpeg, png and webp assets are supported")
        return normalized

    @model_validator(mode="after")
    def validate_file_extension(self) -> "ProductAssetCreate":
        extension = Path(self.file_name).suffix.lower().removeprefix(".")
        if extension not in SUPPORTED_ASSET_TYPES:
            raise ValueError("The file name must use jpg, jpeg, png or webp")
        return self


class ProductAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    file_name: str
    file_path: str
    file_type: str
    created_at: datetime
    content_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None


class ProductRead(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand_kit_version_id: int | None = None
    created_at: datetime
    updated_at: datetime
    assets: list[ProductAssetRead] = Field(default_factory=list)
