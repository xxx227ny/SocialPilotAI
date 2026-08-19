"""Add controlled product media and immutable script-to-video bridge."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_product_media_video_bridge"
down_revision: str | Sequence[str] | None = "0013_qwen_video_script_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("product_assets") as batch_op:
        batch_op.add_column(sa.Column("content_type", sa.String(100)))
        batch_op.add_column(sa.Column("size_bytes", sa.Integer()))
        batch_op.add_column(sa.Column("sha256", sa.String(64)))
        batch_op.add_column(sa.Column("width", sa.Integer()))
        batch_op.add_column(sa.Column("height", sa.Integer()))
        batch_op.add_column(sa.Column("storage_identity", sa.String(200)))
        batch_op.create_index("ix_product_assets_sha256", ["sha256"])
        batch_op.create_unique_constraint(
            "uq_product_assets_storage_identity", ["storage_identity"]
        )

    with op.batch_alter_table("video_projects") as batch_op:
        batch_op.add_column(sa.Column("source_script_version_id", sa.Integer()))
        batch_op.add_column(sa.Column("source_script_content_digest", sa.String(64)))
        batch_op.create_foreign_key(
            "fk_video_projects_source_script_version",
            "video_script_versions",
            ["source_script_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint(
            "uq_video_projects_source_script_version", ["source_script_version_id"]
        )
        batch_op.create_index(
            "ix_video_projects_source_script_version_id", ["source_script_version_id"]
        )

    with op.batch_alter_table("video_render_tasks") as batch_op:
        batch_op.add_column(sa.Column("source_product_asset_id", sa.Integer()))
        batch_op.add_column(sa.Column("source_product_asset_sha256", sa.String(64)))
        batch_op.create_foreign_key(
            "fk_video_render_tasks_source_product_asset",
            "product_assets",
            ["source_product_asset_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_video_render_tasks_source_product_asset_id",
            ["source_product_asset_id"],
        )

    with op.batch_alter_table("video_composition_audio_artifacts") as batch_op:
        batch_op.add_column(sa.Column("natural_duration_ms", sa.Integer()))
        batch_op.create_check_constraint(
            "ck_composition_audio_natural_duration",
            "natural_duration_ms IS NULL OR "
            "(natural_duration_ms > 0 AND natural_duration_ms <= duration_ms)",
        )


def downgrade() -> None:
    with op.batch_alter_table("video_composition_audio_artifacts") as batch_op:
        batch_op.drop_constraint("ck_composition_audio_natural_duration", type_="check")
        batch_op.drop_column("natural_duration_ms")

    with op.batch_alter_table("video_render_tasks") as batch_op:
        batch_op.drop_index("ix_video_render_tasks_source_product_asset_id")
        batch_op.drop_constraint(
            "fk_video_render_tasks_source_product_asset", type_="foreignkey"
        )
        batch_op.drop_column("source_product_asset_sha256")
        batch_op.drop_column("source_product_asset_id")

    with op.batch_alter_table("video_projects") as batch_op:
        batch_op.drop_index("ix_video_projects_source_script_version_id")
        batch_op.drop_constraint(
            "uq_video_projects_source_script_version", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_video_projects_source_script_version", type_="foreignkey"
        )
        batch_op.drop_column("source_script_content_digest")
        batch_op.drop_column("source_script_version_id")

    with op.batch_alter_table("product_assets") as batch_op:
        batch_op.drop_constraint("uq_product_assets_storage_identity", type_="unique")
        batch_op.drop_index("ix_product_assets_sha256")
        for column in (
            "storage_identity",
            "height",
            "width",
            "sha256",
            "size_bytes",
            "content_type",
        ):
            batch_op.drop_column(column)
