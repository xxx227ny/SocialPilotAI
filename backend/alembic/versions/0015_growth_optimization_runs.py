"""Persist versioned internal growth optimization plans."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_growth_optimization_runs"
down_revision: str | Sequence[str] | None = "0014_product_media_video_bridge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_optimization_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("source_context_digest", sa.String(64), nullable=False),
        sa.Column("source_recommendation_digest", sa.String(64), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("actions_json", sa.JSON(), nullable=False),
        sa.Column("current_total_spend", sa.Numeric(14, 2), nullable=False),
        sa.Column("recommended_total_budget", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("execution_scope", sa.String(40), nullable=False),
        sa.Column("external_execution_status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "product_id",
            "idempotency_key",
            name="uq_growth_optimization_product_key",
        ),
        sa.CheckConstraint(
            "status IN ('PROPOSED','ACTIVE','SUPERSEDED')",
            name="ck_growth_optimization_status",
        ),
        sa.CheckConstraint(
            "execution_scope = 'INTERNAL_PLAN_ONLY'",
            name="ck_growth_optimization_execution_scope",
        ),
        sa.CheckConstraint(
            "external_execution_status = 'NOT_CONNECTED'",
            name="ck_growth_optimization_external_status",
        ),
    )
    op.create_index(
        "ix_growth_optimization_runs_product_id",
        "growth_optimization_runs",
        ["product_id"],
    )
    op.create_index(
        "ix_growth_optimization_runs_source_context_digest",
        "growth_optimization_runs",
        ["source_context_digest"],
    )
    op.create_index(
        "uq_growth_optimization_active_product",
        "growth_optimization_runs",
        ["product_id"],
        unique=True,
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_growth_optimization_active_product",
        table_name="growth_optimization_runs",
    )
    op.drop_index(
        "ix_growth_optimization_runs_source_context_digest",
        table_name="growth_optimization_runs",
    )
    op.drop_index(
        "ix_growth_optimization_runs_product_id",
        table_name="growth_optimization_runs",
    )
    op.drop_table("growth_optimization_runs")
