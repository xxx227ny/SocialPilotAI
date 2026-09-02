"""Add region-safe workspace provider profiles."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029_provider_credential_profiles"
down_revision: str | Sequence[str] | None = "0028_brand_kit_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider_credentials") as batch:
        batch.add_column(
            sa.Column(
                "provider_region",
                sa.String(40),
                nullable=False,
                server_default="cn-beijing",
            )
        )
        batch.add_column(
            sa.Column("provider_workspace_ref", sa.String(120), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("provider_credentials") as batch:
        batch.drop_column("provider_workspace_ref")
        batch.drop_column("provider_region")
