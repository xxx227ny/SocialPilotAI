"""Scope social accounts, OAuth state, publishing and TikTok snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027_social_workspace_isolation"
down_revision: str | Sequence[str] | None = "0026_product_workspaces"
branch_labels = None
depends_on = None


TABLES = (
    "social_accounts",
    "oauth_sessions",
    "publish_tasks",
    "tiktok_creator_info_snapshots",
)


def upgrade() -> None:
    op.create_index(
        "uq_execution_jobs_legacy_idempotency",
        "execution_jobs",
        ["idempotency_key"],
        unique=True,
        sqlite_where=sa.text("workspace_id IS NULL"),
        postgresql_where=sa.text("workspace_id IS NULL"),
    )
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("workspace_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                f"fk_{table}_workspace_id",
                "workspaces",
                ["workspace_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch.create_index(f"ix_{table}_workspace_id", ["workspace_id"])

    # Existing product-owned rows inherit the product's workspace. Legacy Demo
    # rows remain NULL and continue to work only when user auth is disabled.
    for table in TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} SET workspace_id = ("
                "SELECT products.workspace_id FROM products "
                f"WHERE products.id = {table}.product_id"
                ") WHERE workspace_id IS NULL"
            )
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_workspace_id")
            batch.drop_constraint(f"fk_{table}_workspace_id", type_="foreignkey")
            batch.drop_column("workspace_id")
    op.drop_index("uq_execution_jobs_legacy_idempotency", table_name="execution_jobs")
