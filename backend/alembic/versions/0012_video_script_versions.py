"""Add immutable script and storyboard version history."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_video_script_versions"
down_revision: str | Sequence[str] | None = "0011_batch_video_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_script_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_video_variant_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.Integer()),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("product_content_digest", sa.String(64), nullable=False),
        sa.Column("strategy_id", sa.Integer()),
        sa.Column("strategy_digest", sa.String(64)),
        sa.Column("copy_matrix_id", sa.Integer()),
        sa.Column("target_platform_copy_digest", sa.String(64)),
        sa.Column("source_video_project_id", sa.Integer()),
        sa.Column("source_video_project_digest", sa.String(64)),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("language", sa.String(35), nullable=False),
        sa.Column("creative_angle", sa.String(300)),
        sa.Column("brand_kit_version_id", sa.Integer()),
        sa.Column("brand_kit_version_digest", sa.String(64)),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("concept", sa.Text(), nullable=False),
        sa.Column("hook", sa.Text(), nullable=False),
        sa.Column("full_narration", sa.Text(), nullable=False),
        sa.Column("cta", sa.Text(), nullable=False),
        sa.Column("full_subtitle_draft", sa.Text(), nullable=False),
        sa.Column("created_by_kind", sa.String(30), nullable=False),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_video_variant_id"], ["batch_video_variants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["video_script_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["marketing_strategies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["copy_matrix_id"], ["copy_matrices.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_video_project_id"], ["video_projects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["brand_kit_version_id"], ["brand_kit_versions.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "batch_video_variant_id",
            "version_number",
            name="uq_video_script_variant_version",
        ),
        sa.UniqueConstraint(
            "batch_video_variant_id",
            "idempotency_key",
            name="uq_video_script_variant_idempotency",
        ),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_video_script_version_positive"
        ),
        sa.CheckConstraint(
            "source_type IN ('MANUAL','VIDEO_PROJECT_IMPORT')",
            name="ck_video_script_source_type",
        ),
        sa.CheckConstraint(
            "created_by_kind IN ('LOCAL_USER','SYSTEM_IMPORT')",
            name="ck_video_script_created_by",
        ),
        sa.CheckConstraint(
            "review_status = 'UNREVIEWED'", name="ck_video_script_review_status"
        ),
    )
    for column in (
        "batch_video_variant_id",
        "parent_version_id",
        "source_digest",
        "content_digest",
    ):
        op.create_index(
            f"ix_video_script_versions_{column}", "video_script_versions", [column]
        )
    op.create_table(
        "video_storyboard_scene_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("video_script_version_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("shot_type", sa.String(120), nullable=False),
        sa.Column("visual_description", sa.Text(), nullable=False),
        sa.Column("action_description", sa.Text(), nullable=False),
        sa.Column("narration", sa.Text(), nullable=False),
        sa.Column("subtitle_draft", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["video_script_version_id"],
            ["video_script_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "video_script_version_id",
            "sequence",
            name="uq_video_storyboard_scene_sequence",
        ),
        sa.CheckConstraint(
            "sequence BETWEEN 1 AND 12", name="ck_video_storyboard_scene_sequence"
        ),
        sa.CheckConstraint(
            "start_ms >= 0 AND end_ms > start_ms",
            name="ck_video_storyboard_scene_timeline",
        ),
    )
    op.create_index(
        "ix_video_storyboard_scene_versions_video_script_version_id",
        "video_storyboard_scene_versions",
        ["video_script_version_id"],
    )
    with op.batch_alter_table("batch_video_variants") as batch_op:
        batch_op.add_column(
            sa.Column("active_script_version_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "script_version_sequence",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_foreign_key(
            "fk_batch_video_variants_active_script_version",
            "video_script_versions",
            ["active_script_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_batch_video_variants_active_script_version_id",
            ["active_script_version_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("batch_video_variants") as batch_op:
        batch_op.drop_index("ix_batch_video_variants_active_script_version_id")
        batch_op.drop_constraint(
            "fk_batch_video_variants_active_script_version", type_="foreignkey"
        )
        batch_op.drop_column("active_script_version_id")
        batch_op.drop_column("script_version_sequence")
    op.drop_table("video_storyboard_scene_versions")
    op.drop_table("video_script_versions")
