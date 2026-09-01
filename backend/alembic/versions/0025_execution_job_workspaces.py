"""Scope execution jobs to the owning workspace."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_execution_job_workspaces"
down_revision: str | Sequence[str] | None = "0024_provider_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("execution_jobs") as batch:
        batch.add_column(sa.Column("workspace_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_execution_jobs_workspace_id",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.drop_constraint("uq_execution_jobs_idempotency", type_="unique")
        batch.create_unique_constraint(
            "uq_execution_jobs_workspace_idempotency",
            ["workspace_id", "idempotency_key"],
        )
        batch.create_index(
            "ix_execution_jobs_workspace_id", ["workspace_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("execution_jobs") as batch:
        batch.drop_index("ix_execution_jobs_workspace_id")
        batch.drop_constraint(
            "uq_execution_jobs_workspace_idempotency", type_="unique"
        )
        batch.create_unique_constraint(
            "uq_execution_jobs_idempotency", ["idempotency_key"]
        )
        batch.drop_constraint("fk_execution_jobs_workspace_id", type_="foreignkey")
        batch.drop_column("workspace_id")
