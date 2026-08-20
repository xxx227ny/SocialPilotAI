from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.product import Product, utc_now
from app.models.strategy import MarketingStrategy

if TYPE_CHECKING:
    from app.models.video import VideoProject

LEGACY_PLATFORMS = {"tiktok", "instagram", "facebook"}
REQUIRED_PLATFORMS = {*LEGACY_PLATFORMS, "pinterest"}


class CopyMatrix(Base):
    __tablename__ = "copy_matrices"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketing_strategy_id: Mapped[int] = mapped_column(
        ForeignKey("marketing_strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    copies: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    product: Mapped[Product] = relationship(back_populates="copy_matrices")
    marketing_strategy: Mapped[MarketingStrategy] = relationship(
        back_populates="copy_matrices"
    )
    video_projects: Mapped[list[VideoProject]] = relationship(
        back_populates="copy_matrix", cascade="all, delete-orphan"
    )

    @validates("copies")
    def validate_copies(
        self, _: str, value: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        platforms = [str(copy.get("platform", "")).casefold() for copy in value]
        platform_set = frozenset(platforms)
        if len(platforms) != len(platform_set) or platform_set not in {
            frozenset(LEGACY_PLATFORMS),
            frozenset(REQUIRED_PLATFORMS),
        }:
            raise ValueError(
                "Copies must contain the legacy three-platform matrix or the "
                "complete four-platform matrix"
            )
        return value
