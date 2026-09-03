"""Make product creation safely repeatable after delivery timeouts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032_product_create_idempotency"
down_revision: str | Sequence[str] | None = "0031_account_action_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("create_request_key", sa.String(100)))
        batch.add_column(sa.Column("create_request_digest", sa.String(64)))
        batch.create_unique_constraint(
            "uq_products_workspace_create_request_key",
            ["workspace_id", "create_request_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.drop_constraint(
            "uq_products_workspace_create_request_key", type_="unique"
        )
        batch.drop_column("create_request_digest")
        batch.drop_column("create_request_key")
