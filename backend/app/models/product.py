from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.brand_kit import BrandKitVersion
    from app.models.campaign import AdCampaign
    from app.models.copy import CopyMatrix
    from app.models.marketing import MarketingBrief
    from app.models.strategy import MarketingStrategy
    from app.models.video import VideoProject


def utc_now() -> datetime:
    return datetime.now(UTC)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    selling_points: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    target_markets: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    brand_kit_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("brand_kit_versions.id", ondelete="RESTRICT"), index=True
    )

    brand_kit_version: Mapped[BrandKitVersion | None] = relationship(
        back_populates="products"
    )

    assets: Mapped[list[ProductAsset]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    marketing_briefs: Mapped[list[MarketingBrief]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    marketing_strategies: Mapped[list[MarketingStrategy]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    copy_matrices: Mapped[list[CopyMatrix]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    ad_campaigns: Mapped[list[AdCampaign]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    video_projects: Mapped[list[VideoProject]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    @validates("name")
    def validate_name(self, _: str, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Product name cannot be empty")
        return value

    @validates("selling_points")
    def validate_selling_points(self, _: str, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("Selling points cannot be empty")
        return value


class ProductAsset(Base):
    __tablename__ = "product_assets"
    __table_args__ = (
        UniqueConstraint("storage_identity", name="uq_product_assets_storage_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    content_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    storage_identity: Mapped[str | None] = mapped_column(String(200))

    product: Mapped[Product] = relationship(back_populates="assets")
