"""Add stable product numbers local to each workspace."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033_workspace_product_numbers"
down_revision: str | Sequence[str] | None = "0032_product_create_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(
            sa.Column(
                "next_product_number",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("display_number", sa.Integer(), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, workspace_id FROM products "
            "ORDER BY workspace_id IS NULL, workspace_id, created_at, id"
        )
    ).mappings()
    counters: dict[int | None, int] = {}
    for row in rows:
        workspace_id = row["workspace_id"]
        number = counters.get(workspace_id, 0) + 1
        counters[workspace_id] = number
        connection.execute(
            sa.text("UPDATE products SET display_number = :number WHERE id = :id"),
            {"number": number, "id": row["id"]},
        )

    for workspace_id, highest in counters.items():
        if workspace_id is None:
            continue
        connection.execute(
            sa.text(
                "UPDATE workspaces SET next_product_number = :next_number "
                "WHERE id = :workspace_id"
            ),
            {"next_number": highest + 1, "workspace_id": workspace_id},
        )

    with op.batch_alter_table("products") as batch:
        batch.create_unique_constraint(
            "uq_products_workspace_display_number",
            ["workspace_id", "display_number"],
        )


def downgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.drop_constraint(
            "uq_products_workspace_display_number", type_="unique"
        )
        batch.drop_column("display_number")
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("next_product_number")
