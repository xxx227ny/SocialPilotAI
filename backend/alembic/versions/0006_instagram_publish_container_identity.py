"""Add Instagram publish container identity and feed choice."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_instagram_publish_container_identity"
down_revision: str | Sequence[str] | None = "0005_qwen_strategy_job_result"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("publish_tasks", recreate="always") as batch:
        batch.add_column(
            sa.Column("provider_container_id", sa.String(length=255), nullable=True),
            insert_after="provider_video_id",
        )
        batch.add_column(
            sa.Column(
                "share_to_feed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            insert_after="resumable_session_ciphertext",
        )
        batch.create_index(
            "ix_publish_tasks_provider_container_id",
            ["provider_container_id"],
            unique=False,
        )
    with op.batch_alter_table("publish_tasks") as batch:
        batch.alter_column("share_to_feed", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("publish_tasks") as batch:
        batch.drop_index("ix_publish_tasks_provider_container_id")
        batch.drop_column("share_to_feed")
        batch.drop_column("provider_container_id")
