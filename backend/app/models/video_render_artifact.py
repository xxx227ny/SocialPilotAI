from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.product import utc_now

if TYPE_CHECKING:
    from app.models.video_render import VideoRenderTask


class VideoRenderArtifact(Base):
    __tablename__ = "video_render_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_render_task_id: Mapped[int] = mapped_column(
        ForeignKey("video_render_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    provider_output_url: Mapped[str | None] = mapped_column(String(2000))
    storage_path: Mapped[str | None] = mapped_column(String(2000))
    artifact_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    video_render_task: Mapped[VideoRenderTask] = relationship(
        back_populates="artifact"
    )
