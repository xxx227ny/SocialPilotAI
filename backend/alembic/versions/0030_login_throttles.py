"""Add persistent login throttling state."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_login_throttles"
down_revision: str | Sequence[str] | None = "0029_provider_credential_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_throttles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_login_throttles_scope_hash",
        "login_throttles",
        ["scope_hash"],
        unique=True,
    )
    op.create_index(
        "ix_login_throttles_locked_until",
        "login_throttles",
        ["locked_until"],
    )


def downgrade() -> None:
    op.drop_table("login_throttles")
