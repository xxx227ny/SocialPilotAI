"""Add TikTok Direct Post creator snapshots and task audit fields."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_tiktok_direct_post"
down_revision: str | Sequence[str] | None = "0007_tiktok_refresh_token_expiry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tiktok_creator_info_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("social_account_id", sa.Integer(), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("provider_identity_digest", sa.String(64), nullable=False),
        sa.Column("creator_username", sa.String(255), nullable=False),
        sa.Column("creator_nickname", sa.String(255), nullable=False),
        sa.Column("privacy_level_options", sa.JSON(), nullable=False),
        sa.Column("comment_disabled", sa.Boolean(), nullable=False),
        sa.Column("duet_disabled", sa.Boolean(), nullable=False),
        sa.Column("stitch_disabled", sa.Boolean(), nullable=False),
        sa.Column("max_video_post_duration_sec", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["social_account_id"], ["social_accounts.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_tiktok_creator_info_snapshots_product_id",
        "tiktok_creator_info_snapshots",
        ["product_id"],
    )
    op.create_index(
        "ix_tiktok_creator_info_snapshots_social_account_id",
        "tiktok_creator_info_snapshots",
        ["social_account_id"],
    )
    op.create_index(
        "ix_tiktok_creator_info_snapshots_request_digest",
        "tiktok_creator_info_snapshots",
        ["request_digest"],
    )
    with op.batch_alter_table("publish_tasks", recreate="always") as batch:
        batch.add_column(
            sa.Column("provider_publish_id", sa.String(255)),
            insert_after="provider_container_id",
        )
        previous = "share_to_feed"
        for name in (
            "disable_comment",
            "disable_duet",
            "disable_stitch",
            "brand_content_toggle",
            "brand_organic_toggle",
        ):
            batch.add_column(
                sa.Column(
                    name,
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
                insert_after=previous,
            )
            previous = name
        batch.create_index(
            "ix_publish_tasks_provider_publish_id", ["provider_publish_id"]
        )
    with op.batch_alter_table("publish_tasks") as batch:
        for name in (
            "disable_comment",
            "disable_duet",
            "disable_stitch",
            "brand_content_toggle",
            "brand_organic_toggle",
        ):
            batch.alter_column(name, server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("publish_tasks") as batch:
        batch.drop_index("ix_publish_tasks_provider_publish_id")
        for name in (
            "brand_organic_toggle",
            "brand_content_toggle",
            "disable_stitch",
            "disable_duet",
            "disable_comment",
            "provider_publish_id",
        ):
            batch.drop_column(name)
    op.drop_index(
        "ix_tiktok_creator_info_snapshots_request_digest",
        table_name="tiktok_creator_info_snapshots",
    )
    op.drop_index(
        "ix_tiktok_creator_info_snapshots_social_account_id",
        table_name="tiktok_creator_info_snapshots",
    )
    op.drop_index(
        "ix_tiktok_creator_info_snapshots_product_id",
        table_name="tiktok_creator_info_snapshots",
    )
    op.drop_table("tiktok_creator_info_snapshots")
