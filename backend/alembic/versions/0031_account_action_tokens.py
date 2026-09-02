"""Add one-time account action tokens."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031_account_action_tokens"
down_revision: str | Sequence[str] | None = "0030_login_throttles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_action_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_account_action_tokens_user_id",
        "account_action_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_account_action_tokens_purpose",
        "account_action_tokens",
        ["purpose"],
    )
    op.create_index(
        "ix_account_action_tokens_token_hash",
        "account_action_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_account_action_tokens_expires_at",
        "account_action_tokens",
        ["expires_at"],
    )
    op.create_index(
        "ix_account_action_tokens_consumed_at",
        "account_action_tokens",
        ["consumed_at"],
    )


def downgrade() -> None:
    op.drop_table("account_action_tokens")
