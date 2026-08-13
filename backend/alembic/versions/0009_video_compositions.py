"""Add immutable local video compositions and final artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_video_compositions"
down_revision: str | Sequence[str] | None = "0008_tiktok_direct_post"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_compositions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("video_project_id", sa.Integer(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("source_chain_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("aspect_ratio", sa.String(20), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("fps_numerator", sa.Integer(), nullable=False),
        sa.Column("fps_denominator", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("safe_error_code", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["video_project_id"], ["video_projects.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_video_compositions_idempotency"
        ),
        sa.CheckConstraint(
            "duration_ms = 15000", name="ck_video_compositions_duration"
        ),
        sa.CheckConstraint(
            "width = 1080 AND height = 1920", name="ck_video_compositions_dimensions"
        ),
        sa.CheckConstraint(
            "fps_numerator = 30 AND fps_denominator = 1",
            name="ck_video_compositions_fps",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','READY','QUEUED','COMPOSING','VERIFYING',"
            "'SUCCEEDED','FAILED','PERSIST_UNKNOWN')",
            name="ck_video_compositions_status",
        ),
    )
    op.create_index(
        "ix_video_compositions_product_id", "video_compositions", ["product_id"]
    )
    op.create_index(
        "ix_video_compositions_video_project_id",
        "video_compositions",
        ["video_project_id"],
    )
    op.create_index(
        "ix_video_compositions_input_digest", "video_compositions", ["input_digest"]
    )
    op.create_index("ix_video_compositions_status", "video_compositions", ["status"])
    op.create_table(
        "video_composition_shots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("composition_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("trim_start_ms", sa.Integer(), nullable=False),
        sa.Column("trim_end_ms", sa.Integer(), nullable=False),
        sa.Column("transition_type", sa.String(20), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("video_project_id", sa.Integer(), nullable=False),
        sa.Column("source_render_task_id", sa.Integer(), nullable=False),
        sa.Column("source_artifact_id", sa.Integer(), nullable=False),
        sa.Column("source_artifact_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["composition_id"], ["video_compositions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["video_project_id"], ["video_projects.id"]),
        sa.ForeignKeyConstraint(["source_render_task_id"], ["video_render_tasks.id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["video_render_artifacts.id"]),
        sa.UniqueConstraint(
            "composition_id", "sequence", name="uq_video_composition_shots_sequence"
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_video_composition_shots_sequence"),
        sa.CheckConstraint(
            "start_ms >= 0 AND end_ms > start_ms AND end_ms <= 15000",
            name="ck_video_composition_shots_timeline",
        ),
        sa.CheckConstraint(
            "trim_start_ms >= 0 AND trim_end_ms > trim_start_ms",
            name="ck_video_composition_shots_trim",
        ),
        sa.CheckConstraint(
            "transition_type = 'cut'", name="ck_video_composition_shots_transition"
        ),
    )
    op.create_index(
        "ix_video_composition_shots_composition_id",
        "video_composition_shots",
        ["composition_id"],
    )
    op.create_table(
        "video_composition_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("composition_id", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(2000), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("fps_numerator", sa.Integer(), nullable=False),
        sa.Column("fps_denominator", sa.Integer(), nullable=False),
        sa.Column("video_codec", sa.String(30), nullable=False),
        sa.Column("pixel_format", sa.String(30), nullable=False),
        sa.Column("audio_codec", sa.String(30), nullable=False),
        sa.Column("audio_sample_rate", sa.Integer(), nullable=False),
        sa.Column("container", sa.String(30), nullable=False),
        sa.Column("source_chain_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["composition_id"], ["video_compositions.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "duration_ms > 0", name="ck_video_composition_artifacts_duration"
        ),
        sa.CheckConstraint(
            "width > 0 AND height > 0", name="ck_video_composition_artifacts_dimensions"
        ),
        sa.CheckConstraint(
            "fps_numerator > 0 AND fps_denominator > 0",
            name="ck_video_composition_artifacts_fps",
        ),
        sa.CheckConstraint(
            "size_bytes > 0", name="ck_video_composition_artifacts_size"
        ),
    )
    op.create_index(
        "ix_video_composition_artifacts_composition_id",
        "video_composition_artifacts",
        ["composition_id"],
        unique=True,
    )
    op.create_index(
        "ix_video_composition_artifacts_sha256",
        "video_composition_artifacts",
        ["sha256"],
    )


def downgrade() -> None:
    op.drop_table("video_composition_artifacts")
    op.drop_table("video_composition_shots")
    op.drop_table("video_compositions")
