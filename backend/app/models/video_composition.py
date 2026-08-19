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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.product import utc_now

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.video import VideoProject
    from app.models.video_render import VideoRenderTask
    from app.models.video_render_artifact import VideoRenderArtifact


COMPOSITION_STATUSES = (
    "DRAFT",
    "READY",
    "QUEUED",
    "COMPOSING",
    "VERIFYING",
    "SUCCEEDED",
    "FAILED",
    "PERSIST_UNKNOWN",
)


class VideoComposition(Base):
    __tablename__ = "video_compositions"
    __table_args__ = (
        CheckConstraint("duration_ms = 15000", name="ck_video_compositions_duration"),
        CheckConstraint(
            "width = 1080 AND height = 1920", name="ck_video_compositions_dimensions"
        ),
        CheckConstraint(
            "fps_numerator = 30 AND fps_denominator = 1",
            name="ck_video_compositions_fps",
        ),
        CheckConstraint(
            "status IN ('DRAFT','READY','QUEUED','COMPOSING','VERIFYING',"
            "'SUCCEEDED','FAILED','PERSIST_UNKNOWN')",
            name="ck_video_compositions_status",
        ),
        UniqueConstraint("idempotency_key", name="uq_video_compositions_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    video_project_id: Mapped[int] = mapped_column(
        ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_chain_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=15000)
    aspect_ratio: Mapped[str] = mapped_column(
        String(20), nullable=False, default="9:16"
    )
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=1080)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=1920)
    fps_numerator: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    fps_denominator: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="READY", index=True
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped[Product] = relationship()
    video_project: Mapped[VideoProject] = relationship()
    shots: Mapped[list[VideoCompositionShot]] = relationship(
        back_populates="composition",
        cascade="all, delete-orphan",
        order_by="VideoCompositionShot.sequence",
    )
    artifact: Mapped[VideoCompositionArtifact | None] = relationship(
        back_populates="composition", cascade="all, delete-orphan", uselist=False
    )


class VideoCompositionShot(Base):
    __tablename__ = "video_composition_shots"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_video_composition_shots_sequence"),
        CheckConstraint(
            "start_ms >= 0 AND end_ms > start_ms AND end_ms <= 15000",
            name="ck_video_composition_shots_timeline",
        ),
        CheckConstraint(
            "trim_start_ms >= 0 AND trim_end_ms > trim_start_ms",
            name="ck_video_composition_shots_trim",
        ),
        CheckConstraint(
            "transition_type = 'cut'", name="ck_video_composition_shots_transition"
        ),
        UniqueConstraint(
            "composition_id", "sequence", name="uq_video_composition_shots_sequence"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("video_compositions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    trim_start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trim_end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    transition_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="cut"
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    video_project_id: Mapped[int] = mapped_column(
        ForeignKey("video_projects.id"), nullable=False
    )
    source_render_task_id: Mapped[int] = mapped_column(
        ForeignKey("video_render_tasks.id"), nullable=False
    )
    source_artifact_id: Mapped[int] = mapped_column(
        ForeignKey("video_render_artifacts.id"), nullable=False
    )
    source_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    composition: Mapped[VideoComposition] = relationship(back_populates="shots")
    source_render_task: Mapped[VideoRenderTask] = relationship()
    source_artifact: Mapped[VideoRenderArtifact] = relationship()


class VideoCompositionArtifact(Base):
    __tablename__ = "video_composition_artifacts"
    __table_args__ = (
        CheckConstraint(
            "duration_ms > 0", name="ck_video_composition_artifacts_duration"
        ),
        CheckConstraint(
            "width > 0 AND height > 0", name="ck_video_composition_artifacts_dimensions"
        ),
        CheckConstraint(
            "fps_numerator > 0 AND fps_denominator > 0",
            name="ck_video_composition_artifacts_fps",
        ),
        CheckConstraint("size_bytes > 0", name="ck_video_composition_artifacts_size"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("video_compositions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    storage_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="video/mp4"
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    fps_numerator: Mapped[int] = mapped_column(Integer, nullable=False)
    fps_denominator: Mapped[int] = mapped_column(Integer, nullable=False)
    video_codec: Mapped[str] = mapped_column(String(30), nullable=False)
    pixel_format: Mapped[str] = mapped_column(String(30), nullable=False)
    audio_codec: Mapped[str] = mapped_column(String(30), nullable=False)
    audio_sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    container: Mapped[str] = mapped_column(String(30), nullable=False)
    source_chain_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    composition: Mapped[VideoComposition] = relationship(back_populates="artifact")


ENHANCEMENT_STATUSES = (
    "QUEUED",
    "ENHANCING",
    "VERIFYING",
    "SUCCEEDED",
    "FAILED",
    "PERSIST_UNKNOWN",
)


class VideoCompositionAudioArtifact(Base):
    __tablename__ = "video_composition_audio_artifacts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('voiceover','music')", name="ck_composition_audio_kind"
        ),
        CheckConstraint("size_bytes > 0", name="ck_composition_audio_size"),
        CheckConstraint("duration_ms > 0", name="ck_composition_audio_duration"),
        CheckConstraint(
            "natural_duration_ms IS NULL OR "
            "(natural_duration_ms > 0 AND natural_duration_ms <= duration_ms)",
            name="ck_composition_audio_natural_duration",
        ),
        CheckConstraint(
            "content_type IN ('audio/wav','audio/mpeg','audio/mp4','audio/x-m4a')",
            name="ck_composition_audio_content_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    video_project_id: Mapped[int] = mapped_column(
        ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("video_compositions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    natural_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    composition: Mapped[VideoComposition] = relationship()


class VideoCompositionEnhancement(Base):
    __tablename__ = "video_composition_enhancements"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_video_composition_enhancements_idempotency"
        ),
        CheckConstraint(
            "status IN ('QUEUED','ENHANCING','VERIFYING','SUCCEEDED','FAILED',"
            "'PERSIST_UNKNOWN')",
            name="ck_video_composition_enhancements_status",
        ),
        CheckConstraint(
            "target_lufs_milli BETWEEN -24000 AND -9000", name="ck_enhance_lufs"
        ),
        CheckConstraint(
            "true_peak_millidb BETWEEN -6000 AND -100", name="ck_enhance_peak"
        ),
        CheckConstraint(
            "ducking_reduction_millidb BETWEEN 0 AND 24000",
            name="ck_enhance_ducking",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    video_project_id: Mapped[int] = mapped_column(
        ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    composition_id: Mapped[int] = mapped_column(
        ForeignKey("video_compositions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_artifact_id: Mapped[int] = mapped_column(
        ForeignKey("video_composition_artifacts.id"), nullable=False
    )
    voiceover_artifact_id: Mapped[int] = mapped_column(
        ForeignKey("video_composition_audio_artifacts.id"), nullable=False
    )
    music_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_composition_audio_artifacts.id")
    )
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_chain_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle_cues_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False
    )
    subtitle_style_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    voiceover_gain_millidb: Mapped[int] = mapped_column(Integer, nullable=False)
    music_gain_millidb: Mapped[int] = mapped_column(Integer, nullable=False)
    ducking_reduction_millidb: Mapped[int] = mapped_column(Integer, nullable=False)
    target_lufs_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    true_peak_millidb: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    composition: Mapped[VideoComposition] = relationship()
    source_artifact: Mapped[VideoCompositionArtifact] = relationship()
    voiceover_artifact: Mapped[VideoCompositionAudioArtifact] = relationship(
        foreign_keys=[voiceover_artifact_id]
    )
    music_artifact: Mapped[VideoCompositionAudioArtifact | None] = relationship(
        foreign_keys=[music_artifact_id]
    )
    subtitle_artifact: Mapped[VideoCompositionSubtitleArtifact | None] = relationship(
        back_populates="enhancement", cascade="all, delete-orphan", uselist=False
    )
    artifact: Mapped[VideoCompositionEnhancementArtifact | None] = relationship(
        back_populates="enhancement", cascade="all, delete-orphan", uselist=False
    )


class VideoCompositionSubtitleArtifact(Base):
    __tablename__ = "video_composition_subtitle_artifacts"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_composition_subtitle_size"),
        CheckConstraint("cue_count > 0", name="ck_composition_subtitle_cues"),
        CheckConstraint("format = 'webvtt'", name="ck_composition_subtitle_format"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    enhancement_id: Mapped[int] = mapped_column(
        ForeignKey("video_composition_enhancements.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    storage_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    cue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    enhancement: Mapped[VideoCompositionEnhancement] = relationship(
        back_populates="subtitle_artifact"
    )


class VideoCompositionEnhancementArtifact(Base):
    __tablename__ = "video_composition_enhancement_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "subtitle_artifact_id",
            name="uq_video_composition_enhancement_artifacts_subtitle_artifact_id",
        ),
        CheckConstraint("size_bytes > 0", name="ck_composition_enhanced_size"),
        CheckConstraint(
            "duration_ms BETWEEN 14966 AND 15034",
            name="ck_composition_enhanced_duration",
        ),
        CheckConstraint(
            "width = 1080 AND height = 1920",
            name="ck_composition_enhanced_dimensions",
        ),
        CheckConstraint(
            "fps_numerator = 30 AND fps_denominator = 1",
            name="ck_composition_enhanced_fps",
        ),
        CheckConstraint(
            "video_codec = 'h264' AND video_profile = 'high' "
            "AND pixel_format = 'yuv420p'",
            name="ck_composition_enhanced_video",
        ),
        CheckConstraint(
            "audio_codec = 'aac' AND audio_profile = 'lc' "
            "AND audio_sample_rate = 48000 AND audio_channels = 2",
            name="ck_composition_enhanced_audio",
        ),
        CheckConstraint(
            "content_type = 'video/mp4' AND instr(container, 'mp4') > 0",
            name="ck_composition_enhanced_container",
        ),
        CheckConstraint(
            "subtitle_format = 'webvtt' AND subtitle_cue_count > 0",
            name="ck_composition_enhanced_subtitles",
        ),
        CheckConstraint(
            "audio_video_sync_offset_ms BETWEEN 0 AND 34 "
            "AND longest_black_segment_ms BETWEEN 0 AND 34",
            name="ck_composition_enhanced_qa",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    enhancement_id: Mapped[int] = mapped_column(
        ForeignKey("video_composition_enhancements.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    subtitle_artifact_id: Mapped[int] = mapped_column(
        ForeignKey("video_composition_subtitle_artifacts.id"),
        nullable=False,
    )
    storage_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    fps_numerator: Mapped[int] = mapped_column(Integer, nullable=False)
    fps_denominator: Mapped[int] = mapped_column(Integer, nullable=False)
    video_codec: Mapped[str] = mapped_column(String(30), nullable=False)
    video_profile: Mapped[str] = mapped_column(String(30), nullable=False)
    pixel_format: Mapped[str] = mapped_column(String(30), nullable=False)
    audio_codec: Mapped[str] = mapped_column(String(30), nullable=False)
    audio_profile: Mapped[str] = mapped_column(String(30), nullable=False)
    audio_sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_channels: Mapped[int] = mapped_column(Integer, nullable=False)
    container: Mapped[str] = mapped_column(String(60), nullable=False)
    measured_lufs_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    measured_true_peak_millidb: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_video_sync_offset_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    longest_black_segment_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    subtitle_format: Mapped[str] = mapped_column(String(20), nullable=False)
    subtitle_cue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    subtitle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_chain_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    enhancement: Mapped[VideoCompositionEnhancement] = relationship(
        back_populates="artifact"
    )
    subtitle_artifact: Mapped[VideoCompositionSubtitleArtifact] = relationship()
