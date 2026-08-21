"""Add auditable sandbox execution and rollback records for growth plans."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_growth_sandbox_executions"
down_revision: str | Sequence[str] | None = "0015_growth_optimization_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_optimization_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "optimization_run_id",
            sa.Integer(),
            sa.ForeignKey("growth_optimization_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("source_context_digest", sa.String(64), nullable=False),
        sa.Column("before_actions_json", sa.JSON(), nullable=False),
        sa.Column("target_actions_json", sa.JSON(), nullable=False),
        sa.Column("result_actions_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("execution_mode", sa.String(20), nullable=False),
        sa.Column("provider_name", sa.String(40), nullable=False),
        sa.Column(
            "external_mutation_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "product_id",
            "idempotency_key",
            name="uq_growth_execution_product_key",
        ),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED','ROLLED_BACK')",
            name="ck_growth_execution_status",
        ),
        sa.CheckConstraint(
            "execution_mode = 'SANDBOX'",
            name="ck_growth_execution_mode",
        ),
        sa.CheckConstraint(
            "provider_name = 'sandbox_ad_adapter'",
            name="ck_growth_execution_provider",
        ),
        sa.CheckConstraint(
            "external_mutation_performed = 0",
            name="ck_growth_execution_no_external_mutation",
        ),
    )
    op.create_index(
        "ix_growth_optimization_executions_product_id",
        "growth_optimization_executions",
        ["product_id"],
    )
    op.create_index(
        "ix_growth_optimization_executions_optimization_run_id",
        "growth_optimization_executions",
        ["optimization_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_growth_optimization_executions_optimization_run_id",
        table_name="growth_optimization_executions",
    )
    op.drop_index(
        "ix_growth_optimization_executions_product_id",
        table_name="growth_optimization_executions",
    )
    op.drop_table("growth_optimization_executions")
