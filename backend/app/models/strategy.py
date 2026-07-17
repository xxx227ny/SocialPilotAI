from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.product import Product, utc_now

if TYPE_CHECKING:
    from app.models.copy import CopyMatrix
    from app.models.video import VideoProject


class MarketingStrategy(Base):
    __tablename__ = "marketing_strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    positioning: Mapped[str] = mapped_column(Text, nullable=False)
    audience_insights: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    angles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    risks: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    product: Mapped[Product] = relationship(back_populates="marketing_strategies")
    copy_matrices: Mapped[list[CopyMatrix]] = relationship(
        back_populates="marketing_strategy", cascade="all, delete-orphan"
    )
    video_projects: Mapped[list[VideoProject]] = relationship(
        back_populates="marketing_strategy", cascade="all, delete-orphan"
    )

    @validates("positioning")
    def validate_positioning(self, _: str, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Positioning cannot be empty")
        return value

    @validates("audience_insights", "angles", "risks", "evidence")
    def validate_list(self, key: str, value: list[str]) -> list[str]:
        if not value or any(not item.strip() for item in value):
            raise ValueError(f"{key} must contain non-empty values")
        return value
