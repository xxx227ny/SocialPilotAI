"""Add provider-free batch video orchestration records."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_batch_video_jobs"
down_revision: str | Sequence[str] | None = "0010_video_composition_enhancements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batch_video_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("variant_count", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("current_stage_cost", sa.Numeric(14, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cost_scope", sa.String(40), nullable=False),
        sa.Column("downstream_provider_cost_status", sa.String(30), nullable=False),
        sa.Column("cost_confirmed", sa.Boolean(), nullable=False),
        sa.Column("frozen_constraints_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("request_digest", name="uq_batch_video_jobs_digest"),
        sa.UniqueConstraint("idempotency_key", name="uq_batch_video_jobs_idempotency"),
        sa.CheckConstraint(
            "variant_count > 0", name="ck_batch_video_jobs_variant_count"
        ),
        sa.CheckConstraint(
            "max_concurrency BETWEEN 1 AND variant_count",
            name="ck_batch_video_jobs_concurrency",
        ),
        sa.CheckConstraint(
            "priority BETWEEN 0 AND 100", name="ck_batch_video_jobs_priority"
        ),
        sa.CheckConstraint(
            "current_stage_cost = 0", name="ck_batch_video_jobs_stage_cost"
        ),
        sa.CheckConstraint(
            "cost_scope = 'orchestration_only'", name="ck_batch_video_jobs_cost_scope"
        ),
        sa.CheckConstraint(
            "downstream_provider_cost_status = 'NOT_ESTIMATED'",
            name="ck_batch_video_jobs_downstream_cost",
        ),
        sa.CheckConstraint(
            "status IN ('WAITING','RUNNING','PAUSED','READY_FOR_SCRIPT',"
            "'PARTIAL_FAILED','FAILED','CANCELLED','MIXED_TERMINAL')",
            name="ck_batch_video_jobs_status",
        ),
    )
    op.create_index("ix_batch_video_jobs_status", "batch_video_jobs", ["status"])
    op.create_table(
        "batch_video_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_video_job_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("variant_index", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("aspect_ratio", sa.String(10), nullable=False),
        sa.Column("language", sa.String(35), nullable=False),
        sa.Column("creative_angle", sa.String(300)),
        sa.Column("brand_kit_version_id", sa.Integer()),
        sa.Column("brand_kit_version_digest", sa.String(64)),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("execution_job_id", sa.Integer()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("result_entity_type", sa.String(80)),
        sa.Column("result_entity_id", sa.Integer()),
        sa.Column("safe_error_code", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["batch_video_job_id"], ["batch_video_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["brand_kit_version_id"], ["brand_kit_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["execution_job_id"], ["execution_jobs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_batch_video_variants_idempotency"
        ),
        sa.UniqueConstraint(
            "execution_job_id", name="uq_batch_video_variants_execution_job"
        ),
        sa.UniqueConstraint(
            "batch_video_job_id",
            "product_id",
            "platform",
            "variant_index",
            name="uq_batch_video_variants_identity",
        ),
        sa.CheckConstraint("variant_index >= 1", name="ck_batch_video_variants_index"),
        sa.CheckConstraint(
            "duration_seconds = 15", name="ck_batch_video_variants_duration"
        ),
        sa.CheckConstraint(
            "aspect_ratio = '9:16'", name="ck_batch_video_variants_aspect"
        ),
        sa.CheckConstraint(
            "platform IN ('youtube','tiktok','instagram')",
            name="ck_batch_video_variants_platform",
        ),
        sa.CheckConstraint(
            "status IN ('WAITING','RUNNING','READY_FOR_SCRIPT','PAUSED',"
            "'FAILED','CANCELLED')",
            name="ck_batch_video_variants_status",
        ),
        sa.CheckConstraint(
            "(result_entity_type IS NULL AND result_entity_id IS NULL) OR "
            "(status = 'READY_FOR_SCRIPT' AND result_entity_type IS NOT NULL "
            "AND result_entity_id IS NOT NULL AND result_entity_id > 0)",
            name="ck_batch_video_variants_result",
        ),
    )
    for column in (
        "batch_video_job_id",
        "product_id",
        "brand_kit_version_id",
        "execution_job_id",
        "status",
    ):
        op.create_index(
            f"ix_batch_video_variants_{column}", "batch_video_variants", [column]
        )


def downgrade() -> None:
    op.drop_table("batch_video_variants")
    op.drop_table("batch_video_jobs")
