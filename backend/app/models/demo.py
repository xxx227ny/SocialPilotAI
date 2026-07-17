from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.product import utc_now


class DemoScenario(Base):
    __tablename__ = "demo_scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(
        String(100), nullable=False, default="preset_fixture"
    )
    fixture_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketing_strategy_id: Mapped[int] = mapped_column(
        ForeignKey("marketing_strategies.id", ondelete="CASCADE"), nullable=False
    )
    copy_matrix_id: Mapped[int] = mapped_column(
        ForeignKey("copy_matrices.id", ondelete="CASCADE"), nullable=False
    )
    video_project_id: Mapped[int] = mapped_column(
        ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False
    )
    campaign_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    growth_recommendation: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
