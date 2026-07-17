from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.product import Product, utc_now


class MarketingBrief(Base):
    __tablename__ = "marketing_briefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(100), nullable=False)
    platforms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    tone: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    product: Mapped[Product] = relationship(back_populates="marketing_briefs")

    @validates("platforms")
    def validate_platforms(self, _: str, value: list[str]) -> list[str]:
        normalized = [platform.casefold() for platform in value]
        if not value or len(normalized) != len(set(normalized)):
            raise ValueError("Platforms must be non-empty and unique")
        return value
