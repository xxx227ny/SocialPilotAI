from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.product import utc_now


class VideoScriptVersion(Base):
    __tablename__ = "video_script_versions"
    __table_args__ = (
        UniqueConstraint(
            "batch_video_variant_id",
            "version_number",
            name="uq_video_script_variant_version",
        ),
        UniqueConstraint(
            "batch_video_variant_id",
            "idempotency_key",
            name="uq_video_script_variant_idempotency",
        ),
        CheckConstraint("version_number >= 1", name="ck_video_script_version_positive"),
        CheckConstraint(
            "source_type IN ('MANUAL','VIDEO_PROJECT_IMPORT')",
            name="ck_video_script_source_type",
        ),
        CheckConstraint(
            "created_by_kind IN ('LOCAL_USER','SYSTEM_IMPORT')",
            name="ck_video_script_created_by",
        ),
        CheckConstraint(
            "review_status = 'UNREVIEWED'", name="ck_video_script_review_status"
        ),
        Index("ix_video_script_versions_content_digest", "content_digest"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_video_variant_id: Mapped[int] = mapped_column(
        ForeignKey("batch_video_variants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_script_versions.id", ondelete="RESTRICT"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("marketing_strategies.id", ondelete="RESTRICT")
    )
    strategy_digest: Mapped[str | None] = mapped_column(String(64))
    copy_matrix_id: Mapped[int | None] = mapped_column(
        ForeignKey("copy_matrices.id", ondelete="RESTRICT")
    )
    target_platform_copy_digest: Mapped[str | None] = mapped_column(String(64))
    source_video_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_projects.id", ondelete="RESTRICT")
    )
    source_video_project_digest: Mapped[str | None] = mapped_column(String(64))
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[str] = mapped_column(String(35), nullable=False)
    creative_angle: Mapped[str | None] = mapped_column(String(300))
    brand_kit_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("brand_kit_versions.id", ondelete="RESTRICT")
    )
    brand_kit_version_digest: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    concept: Mapped[str] = mapped_column(Text, nullable=False)
    hook: Mapped[str] = mapped_column(Text, nullable=False)
    full_narration: Mapped[str] = mapped_column(Text, nullable=False)
    cta: Mapped[str] = mapped_column(Text, nullable=False)
    full_subtitle_draft: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNREVIEWED"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    scenes: Mapped[list[VideoStoryboardSceneVersion]] = relationship(
        order_by="VideoStoryboardSceneVersion.sequence",
        foreign_keys="VideoStoryboardSceneVersion.video_script_version_id",
    )


class VideoStoryboardSceneVersion(Base):
    __tablename__ = "video_storyboard_scene_versions"
    __table_args__ = (
        UniqueConstraint(
            "video_script_version_id",
            "sequence",
            name="uq_video_storyboard_scene_sequence",
        ),
        CheckConstraint(
            "sequence BETWEEN 1 AND 12", name="ck_video_storyboard_scene_sequence"
        ),
        CheckConstraint(
            "start_ms >= 0 AND end_ms > start_ms",
            name="ck_video_storyboard_scene_timeline",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    video_script_version_id: Mapped[int] = mapped_column(
        ForeignKey("video_script_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    shot_type: Mapped[str] = mapped_column(String(120), nullable=False)
    visual_description: Mapped[str] = mapped_column(Text, nullable=False)
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    narration: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle_draft: Mapped[str] = mapped_column(Text, nullable=False)


def _reject_version_mutation(*_: object, **__: object) -> None:
    raise ValueError("Video script version records are immutable")


for immutable in (VideoScriptVersion, VideoStoryboardSceneVersion):
    event.listen(immutable, "before_update", _reject_version_mutation)
    event.listen(immutable, "before_delete", _reject_version_mutation)
