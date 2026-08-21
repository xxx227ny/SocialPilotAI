"""Link stale growth monitoring cycles to their resolving internal plans."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_growth_replan_resolutions"
down_revision: str | Sequence[str] | None = "0018_growth_automation_cycles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table(
        "growth_automation_cycles", recreate="always"
    ) as batch_op:
        batch_op.add_column(sa.Column("resolved_by_optimization_run_id", sa.Integer()))
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True)))
        batch_op.create_foreign_key(
            "fk_growth_cycle_resolved_run",
            "growth_optimization_runs",
            ["resolved_by_optimization_run_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint(
            "uq_growth_cycle_resolved_run", ["resolved_by_optimization_run_id"]
        )
        batch_op.create_check_constraint(
            "ck_growth_cycle_resolution_pair",
            "(resolved_by_optimization_run_id IS NULL AND resolved_at IS NULL) OR "
            "(resolved_by_optimization_run_id IS NOT NULL AND resolved_at IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "growth_automation_cycles", recreate="always"
    ) as batch_op:
        batch_op.drop_constraint("ck_growth_cycle_resolution_pair", type_="check")
        batch_op.drop_constraint("uq_growth_cycle_resolved_run", type_="unique")
        batch_op.drop_constraint("fk_growth_cycle_resolved_run", type_="foreignkey")
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("resolved_by_optimization_run_id")
