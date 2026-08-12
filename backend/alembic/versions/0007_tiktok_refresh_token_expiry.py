"""Add refresh-token expiry for TikTok account binding."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_tiktok_refresh_token_expiry"
down_revision: str | Sequence[str] | None = "0006_instagram_publish_container_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("social_accounts", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True
            ),
            insert_after="token_expires_at",
        )


def downgrade() -> None:
    with op.batch_alter_table("social_accounts") as batch:
        batch.drop_column("refresh_token_expires_at")
