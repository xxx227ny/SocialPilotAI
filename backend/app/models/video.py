from __future__ import annotations

from datetime import datetime
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.copy import CopyMatrix
from app.models.product import Product, utc_now
from app.models.strategy import MarketingStrategy

if TYPE_CHECKING:
    from app.models.video_render import VideoRenderTask


class VideoProject(Base):
    __tablename__ = "video_projects"
    __table_args__ = (
        UniqueConstraint(
            "source_script_version_id",
            name="uq_video_projects_source_script_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketing_strategy_id: Mapped[int] = mapped_column(
        ForeignKey("marketing_strategies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    copy_matrix_id: Mapped[int] = mapped_column(
        ForeignKey("copy_matrices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    concept: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(20), nullable=False)
    scenes: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    cta: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planned")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    source_script_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_script_versions.id", ondelete="RESTRICT"),
        index=True,
    )
    source_script_content_digest: Mapped[str | None] = mapped_column(String(64))

    product: Mapped[Product] = relationship(back_populates="video_projects")
    marketing_strategy: Mapped[MarketingStrategy] = relationship(
        back_populates="video_projects"
    )
    copy_matrix: Mapped[CopyMatrix] = relationship(back_populates="video_projects")
    render_tasks: Mapped[list[VideoRenderTask]] = relationship(
        back_populates="video_project", cascade="all, delete-orphan"
    )
