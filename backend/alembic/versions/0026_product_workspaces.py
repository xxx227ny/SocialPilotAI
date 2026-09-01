"""Scope products to the owning workspace."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_product_workspaces"
down_revision: str | Sequence[str] | None = "0025_execution_job_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("workspace_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_products_workspace_id",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_products_workspace_id", ["workspace_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.drop_index("ix_products_workspace_id")
        batch.drop_constraint("fk_products_workspace_id", type_="foreignkey")
        batch.drop_column("workspace_id")
