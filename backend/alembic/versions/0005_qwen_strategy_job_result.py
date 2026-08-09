"""Add safe business result references for execution jobs."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_qwen_strategy_job_result"
down_revision: str | Sequence[str] | None = "0004_execution_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("execution_jobs") as batch:
        batch.add_column(
            sa.Column("result_entity_type", sa.String(length=80), nullable=True)
        )
        batch.add_column(
            sa.Column("result_entity_id", sa.Integer(), nullable=True)
        )
        batch.create_check_constraint(
            "ck_execution_jobs_result_reference",
            "((result_entity_type IS NULL AND result_entity_id IS NULL) OR "
            "(result_entity_type IS NOT NULL AND result_entity_id IS NOT NULL "
            "AND result_entity_id > 0 AND status = 'SUCCEEDED'))",
        )


def downgrade() -> None:
    with op.batch_alter_table("execution_jobs") as batch:
        batch.drop_constraint(
            "ck_execution_jobs_result_reference", type_="check"
        )
        batch.drop_column("result_entity_id")
        batch.drop_column("result_entity_type")
