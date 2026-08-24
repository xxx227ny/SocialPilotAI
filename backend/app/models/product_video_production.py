from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.product import utc_now


class ProductVideoProductionBatch(Base):
    __tablename__ = "product_video_production_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('WAITING','RUNNING','PAUSED','SUCCEEDED',"
            "'PARTIAL_FAILED','FAILED','CANCELLED')",
            name="ck_product_video_production_batches_status",
        ),
        CheckConstraint(
            "known_estimated_cost >= 0",
            name="ck_product_video_production_batches_cost",
        ),
        CheckConstraint(
            "provider_call_budget > 0",
            name="ck_product_video_production_batches_provider_budget",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_product_video_production_batches_idempotency",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference_product_asset_id: Mapped[int] = mapped_column(
        ForeignKey("product_assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reference_product_asset_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="WAITING", index=True
    )
    known_estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cost_estimate_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cost_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_call_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    frozen_preflight_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[ProductVideoProductionItem]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ProductVideoProductionItem.id",
    )


class ProductVideoProductionItem(Base):
    __tablename__ = "product_video_production_items"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('tiktok','youtube','instagram')",
            name="ck_product_video_production_items_platform",
        ),
        CheckConstraint(
            "status IN ('WAITING','RUNNING','SUCCEEDED','FAILED','CANCELLED')",
            name="ck_product_video_production_items_status",
        ),
        CheckConstraint(
            "stage IN ('QUEUED','GENERATING_IMAGES','PREPARING_VIDEO',"
            "'GENERATING_VIDEO','COMPOSING','GENERATING_VOICEOVER','ENHANCING',"
            "'COMPLETE')",
            name="ck_product_video_production_items_stage",
        ),
        UniqueConstraint(
            "production_batch_id",
            "platform",
            name="uq_product_video_production_items_platform",
        ),
        UniqueConstraint(
            "production_batch_id",
            "batch_video_variant_id",
            name="uq_product_video_production_items_variant",
        ),
        UniqueConstraint(
            "production_batch_id",
            "script_version_id",
            name="uq_product_video_production_items_script",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    production_batch_id: Mapped[int] = mapped_column(
        ForeignKey("product_video_production_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_video_variant_id: Mapped[int] = mapped_column(
        ForeignKey("batch_video_variants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    script_version_id: Mapped[int] = mapped_column(
        ForeignKey("video_script_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="WAITING", index=True
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="QUEUED")
    stage_state_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    video_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_projects.id", ondelete="RESTRICT"), index=True
    )
    cloud_render_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_render_tasks.id", ondelete="RESTRICT"), index=True
    )
    cloud_render_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_render_artifacts.id", ondelete="RESTRICT"), index=True
    )
    composition_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_compositions.id", ondelete="RESTRICT"), index=True
    )
    voiceover_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_composition_audio_artifacts.id", ondelete="RESTRICT"),
        index=True,
    )
    enhancement_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_composition_enhancements.id", ondelete="RESTRICT"),
        index=True,
    )
    final_video_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_composition_enhancement_artifacts.id", ondelete="RESTRICT"),
        index=True,
    )
    subtitle_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_composition_subtitle_artifacts.id", ondelete="RESTRICT"),
        index=True,
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    batch: Mapped[ProductVideoProductionBatch] = relationship(back_populates="items")
