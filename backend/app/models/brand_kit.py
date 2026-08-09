from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.product import utc_now

if TYPE_CHECKING:
    from app.models.product import Product


class BrandKit(Base):
    __tablename__ = "brand_kits"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    versions: Mapped[list[BrandKitVersion]] = relationship(
        back_populates="brand_kit", order_by="BrandKitVersion.version_number"
    )


class BrandKitVersion(Base):
    __tablename__ = "brand_kit_versions"
    __table_args__ = (
        CheckConstraint(
            "version_number >= 1", name="ck_brand_kit_version_number_positive"
        ),
        UniqueConstraint(
            "brand_kit_id", "version_number", name="uq_brand_kit_version_number"
        ),
        UniqueConstraint("brand_kit_id", "digest", name="uq_brand_kit_version_digest"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_kit_id: Mapped[int] = mapped_column(
        ForeignKey("brand_kits.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=False)
    positioning: Mapped[str] = mapped_column(Text, nullable=False)
    default_language: Mapped[str] = mapped_column(String(100), nullable=False)
    brand_tone: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    forbidden_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    target_regions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    audience_guidelines: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    visual_guidelines: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    required_disclosures: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    claims_constraints: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    brand_kit: Mapped[BrandKit] = relationship(back_populates="versions")
    products: Mapped[list[Product]] = relationship(back_populates="brand_kit_version")


def _reject_version_mutation(*_: object, **__: object) -> None:
    raise ValueError("BrandKitVersion records are immutable")


event.listen(BrandKitVersion, "before_update", _reject_version_mutation)
event.listen(BrandKitVersion, "before_delete", _reject_version_mutation)
