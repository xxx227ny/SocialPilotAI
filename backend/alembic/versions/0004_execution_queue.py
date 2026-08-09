"""Add the provider-free persistent execution queue foundation."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_execution_queue"
down_revision: str | Sequence[str] | None = "0003_brand_kit_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("concurrency_key", sa.String(length=200), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("cost_confirmed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner_digest", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_name", sa.String(length=80), nullable=True),
        sa.Column("provider_operation_id", sa.String(length=255), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("safe_error_details", sa.JSON(), nullable=True),
        sa.Column("uncertain", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('QUEUED','PAUSED','RUNNING','SUCCEEDED','FAILED',"
            "'SUBMIT_UNKNOWN','CANCELLED')",
            name="ck_execution_jobs_status",
        ),
        sa.CheckConstraint("priority >= 0", name="ck_execution_jobs_priority"),
        sa.CheckConstraint(
            "estimated_cost >= 0", name="ck_execution_jobs_estimated_cost"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 "
            "AND attempt_count <= max_attempts",
            name="ck_execution_jobs_attempt_counts",
        ),
        sa.CheckConstraint(
            "uncertain = (status = 'SUBMIT_UNKNOWN')",
            name="ck_execution_jobs_uncertain_status",
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND lease_owner_digest IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'RUNNING' AND lease_owner_digest IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_execution_jobs_lease_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_execution_jobs_idempotency"
        ),
    )
    op.create_index(
        "ix_execution_jobs_concurrency_key",
        "execution_jobs",
        ["concurrency_key"],
    )
    op.create_index(
        "ix_execution_jobs_job_type", "execution_jobs", ["job_type"]
    )
    op.create_index(
        "ix_execution_jobs_lease_expires_at",
        "execution_jobs",
        ["lease_expires_at"],
    )
    op.create_index(
        "ix_execution_jobs_queue_order",
        "execution_jobs",
        ["status", "priority", "created_at", "id"],
    )
    op.create_index(
        "ix_execution_jobs_source",
        "execution_jobs",
        ["source_type", "source_id"],
    )
    op.create_index(
        "ix_execution_jobs_status", "execution_jobs", ["status"]
    )
    op.create_index(
        "uq_execution_jobs_running_concurrency_key",
        "execution_jobs",
        ["concurrency_key"],
        unique=True,
        sqlite_where=sa.text(
            "concurrency_key IS NOT NULL AND status = 'RUNNING'"
        ),
        postgresql_where=sa.text(
            "concurrency_key IS NOT NULL AND status = 'RUNNING'"
        ),
    )

    op.create_table(
        "execution_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_job_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("safe_error_details", sa.JSON(), nullable=True),
        sa.Column("provider_call_count", sa.Integer(), nullable=False),
        sa.Column("external_submission_possible", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','FAILED','SUBMIT_UNKNOWN',"
            "'LEASE_EXPIRED')",
            name="ck_execution_attempts_status",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1", name="ck_execution_attempts_number"
        ),
        sa.CheckConstraint(
            "provider_call_count >= 0",
            name="ck_execution_attempts_provider_call_count",
        ),
        sa.ForeignKeyConstraint(
            ["execution_job_id"], ["execution_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "execution_job_id",
            "attempt_number",
            name="uq_execution_attempt_job_number",
        ),
    )
    op.create_index(
        "ix_execution_attempts_execution_job_id",
        "execution_attempts",
        ["execution_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_attempts_execution_job_id", table_name="execution_attempts"
    )
    op.drop_table("execution_attempts")
    op.drop_index(
        "uq_execution_jobs_running_concurrency_key",
        table_name="execution_jobs",
    )
    op.drop_index("ix_execution_jobs_status", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_source", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_queue_order", table_name="execution_jobs")
    op.drop_index(
        "ix_execution_jobs_lease_expires_at", table_name="execution_jobs"
    )
    op.drop_index("ix_execution_jobs_job_type", table_name="execution_jobs")
    op.drop_index(
        "ix_execution_jobs_concurrency_key", table_name="execution_jobs"
    )
    op.drop_table("execution_jobs")
