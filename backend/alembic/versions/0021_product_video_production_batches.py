"""Persist recoverable three-platform product video production batches."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021_product_video_production_batches"
down_revision: str | Sequence[str] | None = "0020_video_project_copy_optional"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_video_production_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reference_product_asset_id",
            sa.Integer(),
            sa.ForeignKey("product_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reference_product_asset_sha256", sa.String(64), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("known_estimated_cost", sa.Numeric(14, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cost_estimate_complete", sa.Boolean(), nullable=False),
        sa.Column("cost_confirmed", sa.Boolean(), nullable=False),
        sa.Column("provider_call_budget", sa.Integer(), nullable=False),
        sa.Column("frozen_preflight_json", sa.JSON(), nullable=False),
        sa.Column("safe_error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('WAITING','RUNNING','PAUSED','SUCCEEDED',"
            "'PARTIAL_FAILED','FAILED','CANCELLED')",
            name="ck_product_video_production_batches_status",
        ),
        sa.CheckConstraint(
            "known_estimated_cost >= 0",
            name="ck_product_video_production_batches_cost",
        ),
        sa.CheckConstraint(
            "provider_call_budget > 0",
            name="ck_product_video_production_batches_provider_budget",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_product_video_production_batches_idempotency",
        ),
    )
    op.create_index(
        "ix_product_video_production_batches_product_id",
        "product_video_production_batches",
        ["product_id"],
    )
    op.create_index(
        "ix_product_video_production_batches_reference_product_asset_id",
        "product_video_production_batches",
        ["reference_product_asset_id"],
    )
    op.create_index(
        "ix_product_video_production_batches_input_digest",
        "product_video_production_batches",
        ["input_digest"],
    )
    op.create_index(
        "ix_product_video_production_batches_status",
        "product_video_production_batches",
        ["status"],
    )

    op.create_table(
        "product_video_production_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "production_batch_id",
            sa.Integer(),
            sa.ForeignKey("product_video_production_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "batch_video_variant_id",
            sa.Integer(),
            sa.ForeignKey("batch_video_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "script_version_id",
            sa.Integer(),
            sa.ForeignKey("video_script_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("stage_state_json", sa.JSON(), nullable=False),
        sa.Column(
            "video_project_id",
            sa.Integer(),
            sa.ForeignKey("video_projects.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "cloud_render_task_id",
            sa.Integer(),
            sa.ForeignKey("video_render_tasks.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "cloud_render_artifact_id",
            sa.Integer(),
            sa.ForeignKey("video_render_artifacts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "composition_id",
            sa.Integer(),
            sa.ForeignKey("video_compositions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "voiceover_artifact_id",
            sa.Integer(),
            sa.ForeignKey("video_composition_audio_artifacts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "enhancement_id",
            sa.Integer(),
            sa.ForeignKey("video_composition_enhancements.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "final_video_artifact_id",
            sa.Integer(),
            sa.ForeignKey(
                "video_composition_enhancement_artifacts.id", ondelete="RESTRICT"
            ),
            nullable=True,
        ),
        sa.Column(
            "subtitle_artifact_id",
            sa.Integer(),
            sa.ForeignKey(
                "video_composition_subtitle_artifacts.id", ondelete="RESTRICT"
            ),
            nullable=True,
        ),
        sa.Column("safe_error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "platform IN ('tiktok','youtube','instagram')",
            name="ck_product_video_production_items_platform",
        ),
        sa.CheckConstraint(
            "status IN ('WAITING','RUNNING','SUCCEEDED','FAILED','CANCELLED')",
            name="ck_product_video_production_items_status",
        ),
        sa.CheckConstraint(
            "stage IN ('QUEUED','GENERATING_IMAGES','PREPARING_VIDEO',"
            "'GENERATING_VIDEO','COMPOSING','GENERATING_VOICEOVER','ENHANCING',"
            "'COMPLETE')",
            name="ck_product_video_production_items_stage",
        ),
        sa.UniqueConstraint(
            "production_batch_id",
            "platform",
            name="uq_product_video_production_items_platform",
        ),
        sa.UniqueConstraint(
            "production_batch_id",
            "batch_video_variant_id",
            name="uq_product_video_production_items_variant",
        ),
        sa.UniqueConstraint(
            "production_batch_id",
            "script_version_id",
            name="uq_product_video_production_items_script",
        ),
    )
    for column in (
        "production_batch_id",
        "batch_video_variant_id",
        "script_version_id",
        "status",
        "video_project_id",
        "cloud_render_task_id",
        "cloud_render_artifact_id",
        "composition_id",
        "voiceover_artifact_id",
        "enhancement_id",
        "final_video_artifact_id",
        "subtitle_artifact_id",
    ):
        op.create_index(
            f"ix_product_video_production_items_{column}",
            "product_video_production_items",
            [column],
        )


def downgrade() -> None:
    op.drop_table("product_video_production_items")
    op.drop_table("product_video_production_batches")
