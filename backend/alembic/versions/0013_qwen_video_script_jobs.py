"""Add controlled Qwen script generation provenance and submission state."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_qwen_video_script_jobs"
down_revision: str | Sequence[str] | None = "0012_video_script_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("batch_video_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "qwen_script_call_quota",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "qwen_script_calls_reserved",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_check_constraint(
            "ck_batch_video_jobs_qwen_script_quota",
            "qwen_script_calls_reserved >= 0 AND "
            "qwen_script_calls_reserved <= qwen_script_call_quota",
        )

    with op.batch_alter_table("execution_attempts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "provider_submission_state",
                sa.String(30),
                nullable=False,
                server_default="NOT_STARTED",
            )
        )
        batch_op.create_check_constraint(
            "ck_execution_attempts_provider_submission_state",
            "provider_submission_state IN ('NOT_STARTED','NOT_SUBMITTED',"
            "'EXPLICIT_FAILURE','RESPONSE_RECEIVED','SUBMIT_UNKNOWN')",
        )

    with op.batch_alter_table("video_script_versions") as batch_op:
        batch_op.drop_constraint("ck_video_script_source_type", type_="check")
        batch_op.drop_constraint("ck_video_script_created_by", type_="check")
        batch_op.create_check_constraint(
            "ck_video_script_source_type",
            "source_type IN ('MANUAL','VIDEO_PROJECT_IMPORT','QWEN_GENERATED')",
        )
        batch_op.create_check_constraint(
            "ck_video_script_created_by",
            "created_by_kind IN ('LOCAL_USER','SYSTEM_IMPORT','QWEN_PROVIDER')",
        )
        batch_op.add_column(sa.Column("source_execution_job_id", sa.Integer()))
        batch_op.add_column(sa.Column("prompt_snapshot_json", sa.JSON()))
        batch_op.add_column(sa.Column("prompt_digest", sa.String(64)))
        batch_op.add_column(sa.Column("provider_name", sa.String(80)))
        batch_op.add_column(sa.Column("provider_model", sa.String(120)))
        batch_op.add_column(sa.Column("provider_response_digest", sa.String(64)))
        batch_op.create_foreign_key(
            "fk_video_script_versions_source_execution_job",
            "execution_jobs",
            ["source_execution_job_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint(
            "uq_video_script_source_execution_job", ["source_execution_job_id"]
        )
        batch_op.create_index(
            "ix_video_script_versions_source_execution_job_id",
            ["source_execution_job_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("video_script_versions") as batch_op:
        batch_op.drop_index("ix_video_script_versions_source_execution_job_id")
        batch_op.drop_constraint("uq_video_script_source_execution_job", type_="unique")
        batch_op.drop_constraint(
            "fk_video_script_versions_source_execution_job", type_="foreignkey"
        )
        for column in (
            "provider_response_digest",
            "provider_model",
            "provider_name",
            "prompt_digest",
            "prompt_snapshot_json",
            "source_execution_job_id",
        ):
            batch_op.drop_column(column)
        batch_op.drop_constraint("ck_video_script_created_by", type_="check")
        batch_op.drop_constraint("ck_video_script_source_type", type_="check")
        batch_op.create_check_constraint(
            "ck_video_script_created_by",
            "created_by_kind IN ('LOCAL_USER','SYSTEM_IMPORT')",
        )
        batch_op.create_check_constraint(
            "ck_video_script_source_type",
            "source_type IN ('MANUAL','VIDEO_PROJECT_IMPORT')",
        )

    with op.batch_alter_table("execution_attempts") as batch_op:
        batch_op.drop_constraint(
            "ck_execution_attempts_provider_submission_state", type_="check"
        )
        batch_op.drop_column("provider_submission_state")

    with op.batch_alter_table("batch_video_jobs") as batch_op:
        batch_op.drop_constraint("ck_batch_video_jobs_qwen_script_quota", type_="check")
        batch_op.drop_column("qwen_script_calls_reserved")
        batch_op.drop_column("qwen_script_call_quota")
