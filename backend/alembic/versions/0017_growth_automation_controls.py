"""Add bounded automatic sandbox controls for growth optimization."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_growth_automation_controls"
down_revision: str | Sequence[str] | None = "0016_growth_sandbox_executions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "growth_optimization_executions",
        sa.Column(
            "trigger_kind",
            sa.String(24),
            nullable=False,
            server_default="MANUAL_CONFIRMATION",
        ),
    )
    op.create_table(
        "growth_automation_controls",
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column(
            "kill_switch_engaged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("maximum_total_budget", sa.Numeric(14, 2), nullable=False),
        sa.Column("maximum_budget_change_pct", sa.Numeric(6, 4), nullable=False),
        sa.Column("maximum_bid_adjustment_pct", sa.Numeric(6, 4), nullable=False),
        sa.Column(
            "last_execution_id",
            sa.Integer(),
            sa.ForeignKey("growth_optimization_executions.id", ondelete="SET NULL"),
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mode IN ('MANUAL','AUTO_SANDBOX')",
            name="ck_growth_automation_mode",
        ),
        sa.CheckConstraint(
            "maximum_total_budget > 0",
            name="ck_growth_automation_total_budget",
        ),
        sa.CheckConstraint(
            "maximum_budget_change_pct >= 0 AND maximum_budget_change_pct <= 0.5",
            name="ck_growth_automation_budget_change",
        ),
        sa.CheckConstraint(
            "maximum_bid_adjustment_pct >= 0 AND maximum_bid_adjustment_pct <= 0.5",
            name="ck_growth_automation_bid_adjustment",
        ),
    )


def downgrade() -> None:
    op.drop_table("growth_automation_controls")
    op.drop_column("growth_optimization_executions", "trigger_kind")
