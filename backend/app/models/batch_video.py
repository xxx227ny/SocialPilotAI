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


class BatchVideoJob(Base):
    __tablename__ = "batch_video_jobs"
    __table_args__ = (
        UniqueConstraint("request_digest", name="uq_batch_video_jobs_digest"),
        UniqueConstraint("idempotency_key", name="uq_batch_video_jobs_idempotency"),
        CheckConstraint("variant_count > 0", name="ck_batch_video_jobs_variant_count"),
        CheckConstraint(
            "max_concurrency BETWEEN 1 AND variant_count",
            name="ck_batch_video_jobs_concurrency",
        ),
        CheckConstraint(
            "priority BETWEEN 0 AND 100", name="ck_batch_video_jobs_priority"
        ),
        CheckConstraint(
            "current_stage_cost = 0", name="ck_batch_video_jobs_stage_cost"
        ),
        CheckConstraint(
            "cost_scope = 'orchestration_only'", name="ck_batch_video_jobs_cost_scope"
        ),
        CheckConstraint(
            "downstream_provider_cost_status = 'NOT_ESTIMATED'",
            name="ck_batch_video_jobs_downstream_cost",
        ),
        CheckConstraint(
            "status IN ('WAITING','RUNNING','PAUSED','READY_FOR_SCRIPT',"
            "'PARTIAL_FAILED','FAILED','CANCELLED','MIXED_TERMINAL')",
            name="ck_batch_video_jobs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="WAITING", index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    variant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    current_stage_cost: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=Decimal("0")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    cost_scope: Mapped[str] = mapped_column(
        String(40), nullable=False, default="orchestration_only"
    )
    downstream_provider_cost_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="NOT_ESTIMATED"
    )
    cost_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    frozen_constraints_json: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    variants: Mapped[list[BatchVideoVariant]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="BatchVideoVariant.id",
    )


class BatchVideoVariant(Base):
    __tablename__ = "batch_video_variants"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_batch_video_variants_idempotency"),
        UniqueConstraint(
            "execution_job_id", name="uq_batch_video_variants_execution_job"
        ),
        UniqueConstraint(
            "batch_video_job_id",
            "product_id",
            "platform",
            "variant_index",
            name="uq_batch_video_variants_identity",
        ),
        CheckConstraint("variant_index >= 1", name="ck_batch_video_variants_index"),
        CheckConstraint(
            "duration_seconds = 15", name="ck_batch_video_variants_duration"
        ),
        CheckConstraint("aspect_ratio = '9:16'", name="ck_batch_video_variants_aspect"),
        CheckConstraint(
            "platform IN ('youtube','tiktok','instagram')",
            name="ck_batch_video_variants_platform",
        ),
        CheckConstraint(
            "status IN ('WAITING','RUNNING','READY_FOR_SCRIPT','PAUSED',"
            "'FAILED','CANCELLED')",
            name="ck_batch_video_variants_status",
        ),
        CheckConstraint(
            "(result_entity_type IS NULL AND result_entity_id IS NULL) OR "
            "(status = 'READY_FOR_SCRIPT' AND result_entity_type IS NOT NULL "
            "AND result_entity_id IS NOT NULL AND result_entity_id > 0)",
            name="ck_batch_video_variants_result",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_video_job_id: Mapped[int] = mapped_column(
        ForeignKey("batch_video_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    variant_index: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(10), nullable=False)
    language: Mapped[str] = mapped_column(String(35), nullable=False)
    creative_angle: Mapped[str | None] = mapped_column(String(300))
    brand_kit_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("brand_kit_versions.id", ondelete="RESTRICT"), index=True
    )
    brand_kit_version_digest: Mapped[str | None] = mapped_column(String(64))
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    execution_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("execution_jobs.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="WAITING", index=True
    )
    result_entity_type: Mapped[str | None] = mapped_column(String(80))
    result_entity_id: Mapped[int | None] = mapped_column(Integer)
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_script_version_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "video_script_versions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_batch_video_variants_active_script_version",
        ),
        index=True,
    )
    script_version_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    batch: Mapped[BatchVideoJob] = relationship(back_populates="variants")
    execution_job = relationship("ExecutionJob", foreign_keys=[execution_job_id])
