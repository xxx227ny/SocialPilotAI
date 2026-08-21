"""Persist bounded growth monitoring schedules and cycle audits."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_growth_automation_cycles"
down_revision: str | Sequence[str] | None = "0017_growth_automation_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table(
        "growth_automation_controls", recreate="always"
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "monitoring_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "evaluation_interval_seconds",
                sa.Integer(),
                nullable=False,
                server_default="900",
            )
        )
        batch_op.add_column(sa.Column("next_evaluation_at", sa.DateTime(timezone=True)))
        batch_op.create_check_constraint(
            "ck_growth_automation_interval",
            "evaluation_interval_seconds >= 60 "
            "AND evaluation_interval_seconds <= 86400",
        )
    op.create_table(
        "growth_automation_cycles",
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
            sa.ForeignKey("growth_optimization_runs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "execution_id",
            sa.Integer(),
            sa.ForeignKey("growth_optimization_executions.id", ondelete="SET NULL"),
        ),
        sa.Column("cycle_key", sa.String(160), nullable=False),
        sa.Column("context_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(28), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_evaluation_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "execution_mode", sa.String(20), nullable=False, server_default="SANDBOX"
        ),
        sa.Column(
            "external_mutation_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.UniqueConstraint(
            "product_id", "cycle_key", name="uq_growth_cycle_product_key"
        ),
        sa.CheckConstraint(
            "status IN ('EXECUTED','NO_CHANGE','REPLAN_REQUIRED','KILL_SWITCHED',"
            "'MANUAL_REVIEW_REQUIRED','NO_ACTIVE_PLAN')",
            name="ck_growth_cycle_status",
        ),
        sa.CheckConstraint("execution_mode = 'SANDBOX'", name="ck_growth_cycle_mode"),
        sa.CheckConstraint(
            "external_mutation_performed = 0",
            name="ck_growth_cycle_no_external_mutation",
        ),
    )
    op.create_index(
        "ix_growth_automation_cycles_product_id",
        "growth_automation_cycles",
        ["product_id"],
    )
    op.create_index(
        "ix_growth_automation_cycles_observed_at",
        "growth_automation_cycles",
        ["observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_growth_automation_cycles_observed_at", table_name="growth_automation_cycles"
    )
    op.drop_index(
        "ix_growth_automation_cycles_product_id", table_name="growth_automation_cycles"
    )
    op.drop_table("growth_automation_cycles")
    with op.batch_alter_table(
        "growth_automation_controls", recreate="always"
    ) as batch_op:
        batch_op.drop_constraint("ck_growth_automation_interval", type_="check")
        batch_op.drop_column("next_evaluation_at")
        batch_op.drop_column("evaluation_interval_seconds")
        batch_op.drop_column("monitoring_enabled")
