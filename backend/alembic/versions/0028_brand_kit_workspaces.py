"""Scope brand kits to their owning workspace."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_brand_kit_workspaces"
down_revision: str | Sequence[str] | None = "0027_social_workspace_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("brand_kits") as batch:
        batch.add_column(sa.Column("workspace_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_brand_kits_workspace_id",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_brand_kits_workspace_id", ["workspace_id"])

    # Recover ownership only when every Product bound to a kit belongs to one
    # unambiguous workspace. Legacy Demo kits remain unscoped.
    op.execute(
        sa.text(
            "UPDATE brand_kits SET workspace_id = ("
            "SELECT MIN(products.workspace_id) "
            "FROM brand_kit_versions "
            "JOIN products ON products.brand_kit_version_id = brand_kit_versions.id "
            "WHERE brand_kit_versions.brand_kit_id = brand_kits.id"
            ") WHERE 1 = ("
            "SELECT COUNT(DISTINCT products.workspace_id) "
            "FROM brand_kit_versions "
            "JOIN products ON products.brand_kit_version_id = brand_kit_versions.id "
            "WHERE brand_kit_versions.brand_kit_id = brand_kits.id "
            "AND products.workspace_id IS NOT NULL"
            ")"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("brand_kits") as batch:
        batch.drop_index("ix_brand_kits_workspace_id")
        batch.drop_constraint("fk_brand_kits_workspace_id", type_="foreignkey")
        batch.drop_column("workspace_id")
