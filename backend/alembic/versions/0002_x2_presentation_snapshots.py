"""Add immutable X2 PresentationSnapshot storage."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_x2_presentation_snapshots"
down_revision: str | Sequence[str] | None = "0001_pre_x2_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "presentation_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("marketing_brief_id", sa.Integer(), nullable=True),
        sa.Column("marketing_strategy_id", sa.Integer(), nullable=True),
        sa.Column("copy_matrix_id", sa.Integer(), nullable=True),
        sa.Column("video_project_id", sa.Integer(), nullable=True),
        sa.Column("render_task_id", sa.Integer(), nullable=True),
        sa.Column("artifact_id", sa.Integer(), nullable=True),
        sa.Column("publish_task_id", sa.Integer(), nullable=True),
        sa.Column("campaign_ids", sa.JSON(), nullable=False),
        sa.Column("missing_sections", sa.JSON(), nullable=False),
        sa.Column("snapshot_payload", sa.JSON(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_snapshot_path", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_presentation_snapshots_digest",
        "presentation_snapshots",
        ["digest"],
        unique=True,
    )
    op.create_index(
        "ix_presentation_snapshots_product_id", "presentation_snapshots", ["product_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_presentation_snapshots_product_id", table_name="presentation_snapshots"
    )
    op.drop_index(
        "ix_presentation_snapshots_digest", table_name="presentation_snapshots"
    )
    op.drop_table("presentation_snapshots")
