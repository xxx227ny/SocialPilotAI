"""Add encrypted workspace-scoped provider credentials."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_provider_credentials"
down_revision: str | Sequence[str] | None = "0023_user_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("encryption_key_id", sa.String(100), nullable=False),
        sa.Column("secret_hint", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            name="uq_provider_credential_workspace",
        ),
    )
    op.create_index(
        "ix_provider_credentials_workspace_id",
        "provider_credentials",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_table("provider_credentials")
