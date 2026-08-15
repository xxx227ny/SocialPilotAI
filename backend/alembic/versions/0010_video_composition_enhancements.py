"""Add immutable voice, music, subtitle, and mixed composition artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_video_composition_enhancements"
down_revision: str | Sequence[str] | None = "0009_video_compositions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_composition_audio_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("video_project_id", sa.Integer(), nullable=False),
        sa.Column("composition_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("storage_path", sa.String(2000), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["video_project_id"], ["video_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["composition_id"], ["video_compositions.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "kind IN ('voiceover','music')", name="ck_composition_audio_kind"
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_composition_audio_size"),
        sa.CheckConstraint("duration_ms > 0", name="ck_composition_audio_duration"),
        sa.CheckConstraint(
            "content_type IN ('audio/wav','audio/mpeg','audio/mp4','audio/x-m4a')",
            name="ck_composition_audio_content_type",
        ),
    )
    for column in ("product_id", "video_project_id", "composition_id", "sha256"):
        op.create_index(
            f"ix_video_composition_audio_artifacts_{column}",
            "video_composition_audio_artifacts",
            [column],
        )
    op.create_table(
        "video_composition_enhancements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("video_project_id", sa.Integer(), nullable=False),
        sa.Column("composition_id", sa.Integer(), nullable=False),
        sa.Column("source_artifact_id", sa.Integer(), nullable=False),
        sa.Column("voiceover_artifact_id", sa.Integer(), nullable=False),
        sa.Column("music_artifact_id", sa.Integer()),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("source_chain_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("subtitle_cues_json", sa.JSON(), nullable=False),
        sa.Column("subtitle_style_json", sa.JSON(), nullable=False),
        sa.Column("voiceover_gain_millidb", sa.Integer(), nullable=False),
        sa.Column("music_gain_millidb", sa.Integer(), nullable=False),
        sa.Column("ducking_reduction_millidb", sa.Integer(), nullable=False),
        sa.Column("target_lufs_milli", sa.Integer(), nullable=False),
        sa.Column("true_peak_millidb", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("safe_error_code", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["video_project_id"], ["video_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["composition_id"], ["video_compositions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["video_composition_artifacts.id"]
        ),
        sa.ForeignKeyConstraint(
            ["voiceover_artifact_id"], ["video_composition_audio_artifacts.id"]
        ),
        sa.ForeignKeyConstraint(
            ["music_artifact_id"], ["video_composition_audio_artifacts.id"]
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_video_composition_enhancements_idempotency"
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','ENHANCING','VERIFYING','SUCCEEDED','FAILED',"
            "'PERSIST_UNKNOWN')",
            name="ck_video_composition_enhancements_status",
        ),
        sa.CheckConstraint(
            "target_lufs_milli BETWEEN -24000 AND -9000", name="ck_enhance_lufs"
        ),
        sa.CheckConstraint(
            "true_peak_millidb BETWEEN -6000 AND -100", name="ck_enhance_peak"
        ),
        sa.CheckConstraint(
            "ducking_reduction_millidb BETWEEN 0 AND 24000",
            name="ck_enhance_ducking",
        ),
    )
    for column in (
        "product_id",
        "video_project_id",
        "composition_id",
        "input_digest",
        "status",
    ):
        op.create_index(
            f"ix_video_composition_enhancements_{column}",
            "video_composition_enhancements",
            [column],
        )
    op.create_table(
        "video_composition_subtitle_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enhancement_id", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(2000), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("cue_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["enhancement_id"],
            ["video_composition_enhancements.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_composition_subtitle_size"),
        sa.CheckConstraint("cue_count > 0", name="ck_composition_subtitle_cues"),
        sa.CheckConstraint("format = 'webvtt'", name="ck_composition_subtitle_format"),
    )
    op.create_index(
        "ix_video_composition_subtitle_artifacts_enhancement_id",
        "video_composition_subtitle_artifacts",
        ["enhancement_id"],
        unique=True,
    )
    op.create_index(
        "ix_video_composition_subtitle_artifacts_sha256",
        "video_composition_subtitle_artifacts",
        ["sha256"],
    )
    op.create_table(
        "video_composition_enhancement_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enhancement_id", sa.Integer(), nullable=False),
        sa.Column("subtitle_artifact_id", sa.Integer(), nullable=False),
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
        sa.Column("video_profile", sa.String(30), nullable=False),
        sa.Column("pixel_format", sa.String(30), nullable=False),
        sa.Column("audio_codec", sa.String(30), nullable=False),
        sa.Column("audio_profile", sa.String(30), nullable=False),
        sa.Column("audio_sample_rate", sa.Integer(), nullable=False),
        sa.Column("audio_channels", sa.Integer(), nullable=False),
        sa.Column("container", sa.String(60), nullable=False),
        sa.Column("measured_lufs_milli", sa.Integer(), nullable=False),
        sa.Column("measured_true_peak_millidb", sa.Integer(), nullable=False),
        sa.Column("audio_video_sync_offset_ms", sa.Integer(), nullable=False),
        sa.Column("longest_black_segment_ms", sa.Integer(), nullable=False),
        sa.Column("subtitle_format", sa.String(20), nullable=False),
        sa.Column("subtitle_cue_count", sa.Integer(), nullable=False),
        sa.Column("subtitle_sha256", sa.String(64), nullable=False),
        sa.Column("source_chain_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["enhancement_id"],
            ["video_composition_enhancements.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subtitle_artifact_id"], ["video_composition_subtitle_artifacts.id"]
        ),
        sa.UniqueConstraint(
            "subtitle_artifact_id",
            name=(
                "uq_video_composition_enhancement_artifacts_subtitle_artifact_id"
            ),
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_composition_enhanced_size"),
        sa.CheckConstraint(
            "duration_ms BETWEEN 14966 AND 15034",
            name="ck_composition_enhanced_duration",
        ),
        sa.CheckConstraint(
            "width = 1080 AND height = 1920",
            name="ck_composition_enhanced_dimensions",
        ),
        sa.CheckConstraint(
            "fps_numerator = 30 AND fps_denominator = 1",
            name="ck_composition_enhanced_fps",
        ),
        sa.CheckConstraint(
            "video_codec = 'h264' AND video_profile = 'high' "
            "AND pixel_format = 'yuv420p'",
            name="ck_composition_enhanced_video",
        ),
        sa.CheckConstraint(
            "audio_codec = 'aac' AND audio_profile = 'lc' "
            "AND audio_sample_rate = 48000 AND audio_channels = 2",
            name="ck_composition_enhanced_audio",
        ),
        sa.CheckConstraint(
            "content_type = 'video/mp4' AND instr(container, 'mp4') > 0",
            name="ck_composition_enhanced_container",
        ),
        sa.CheckConstraint(
            "subtitle_format = 'webvtt' AND subtitle_cue_count > 0",
            name="ck_composition_enhanced_subtitles",
        ),
        sa.CheckConstraint(
            "audio_video_sync_offset_ms BETWEEN 0 AND 34 "
            "AND longest_black_segment_ms BETWEEN 0 AND 34",
            name="ck_composition_enhanced_qa",
        ),
    )
    op.create_index(
        "ix_video_composition_enhancement_artifacts_enhancement_id",
        "video_composition_enhancement_artifacts",
        ["enhancement_id"],
        unique=True,
    )
    op.create_index(
        "ix_video_composition_enhancement_artifacts_sha256",
        "video_composition_enhancement_artifacts",
        ["sha256"],
    )


def downgrade() -> None:
    op.drop_table("video_composition_enhancement_artifacts")
    op.drop_table("video_composition_subtitle_artifacts")
    op.drop_table("video_composition_enhancements")
    op.drop_table("video_composition_audio_artifacts")
