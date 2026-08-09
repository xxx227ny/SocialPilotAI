from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BrandKitVersionInput(BaseModel):
    brand_name: str = Field(min_length=1, max_length=200)
    positioning: str = Field(min_length=1, max_length=4000)
    default_language: str = Field(min_length=1, max_length=100)
    brand_tone: str = Field(min_length=1, max_length=2000)
    preferred_terms: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    target_regions: list[str] = Field(default_factory=list)
    audience_guidelines: list[str] = Field(default_factory=list)
    visual_guidelines: list[str] = Field(default_factory=list)
    required_disclosures: list[str] = Field(default_factory=list)
    claims_constraints: list[str] = Field(default_factory=list)


class BrandKitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: BrandKitVersionInput


class BrandKitVersionRead(BrandKitVersionInput):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand_kit_id: int
    version_number: int
    digest: str
    created_at: datetime


class BrandKitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    updated_at: datetime
    versions: list[BrandKitVersionRead] = Field(default_factory=list)


class BrandKitVersionCreateRead(BaseModel):
    version: BrandKitVersionRead
    reused: bool


class ProductBrandKitBinding(BaseModel):
    brand_kit_id: int = Field(gt=0)
    brand_kit_version_id: int = Field(gt=0)
