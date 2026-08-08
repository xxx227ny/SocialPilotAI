"""Create the complete pre-X2 SocialPilot runtime schema."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_pre_x2_runtime"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("selling_points", sa.JSON(), nullable=False),
        sa.Column("target_markets", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_name", "products", ["name"])

    op.create_table(
        "ad_campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=100), nullable=False),
        sa.Column("campaign_name", sa.String(length=300), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("conversions", sa.Integer(), nullable=False),
        sa.Column("spend", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("revenue", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "impressions >= 0", name="ck_campaign_impressions_nonnegative"
        ),
        sa.CheckConstraint("clicks >= 0", name="ck_campaign_clicks_nonnegative"),
        sa.CheckConstraint(
            "conversions >= 0", name="ck_campaign_conversions_nonnegative"
        ),
        sa.CheckConstraint("spend >= 0", name="ck_campaign_spend_nonnegative"),
        sa.CheckConstraint("revenue >= 0", name="ck_campaign_revenue_nonnegative"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ad_campaigns_date", "ad_campaigns", ["date"])
    op.create_index("ix_ad_campaigns_platform", "ad_campaigns", ["platform"])
    op.create_index("ix_ad_campaigns_product_id", "ad_campaigns", ["product_id"])

    op.create_table(
        "marketing_briefs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=100), nullable=False),
        sa.Column("platforms", sa.JSON(), nullable=False),
        sa.Column("tone", sa.String(length=300), nullable=False),
        sa.Column("objective", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_marketing_briefs_product_id", "marketing_briefs", ["product_id"]
    )

    op.create_table(
        "marketing_strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("positioning", sa.Text(), nullable=False),
        sa.Column("audience_insights", sa.JSON(), nullable=False),
        sa.Column("angles", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_marketing_strategies_product_id",
        "marketing_strategies",
        ["product_id"],
    )

    op.create_table(
        "oauth_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("state_digest", sa.String(length=64), nullable=False),
        sa.Column("browser_session_digest", sa.String(length=64), nullable=False),
        sa.Column("pkce_verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("redirect_path", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oauth_sessions_product_id", "oauth_sessions", ["product_id"])
    op.create_index(
        "ix_oauth_sessions_state_digest",
        "oauth_sessions",
        ["state_digest"],
        unique=True,
    )

    op.create_table(
        "product_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_assets_product_id", "product_assets", ["product_id"])

    op.create_table(
        "social_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("provider_account_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connection_status", sa.String(length=30), nullable=False),
        sa.Column("encryption_key_id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "platform",
            "provider_account_id",
            name="uq_social_account_product_platform_provider",
        ),
    )
    op.create_index(
        "ix_social_accounts_connection_status",
        "social_accounts",
        ["connection_status"],
    )
    op.create_index("ix_social_accounts_platform", "social_accounts", ["platform"])
    op.create_index("ix_social_accounts_product_id", "social_accounts", ["product_id"])
    op.create_index(
        "ix_social_accounts_provider_account_id",
        "social_accounts",
        ["provider_account_id"],
    )

    op.create_table(
        "copy_matrices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("marketing_strategy_id", sa.Integer(), nullable=False),
        sa.Column("copies", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["marketing_strategy_id"],
            ["marketing_strategies.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_copy_matrices_marketing_strategy_id",
        "copy_matrices",
        ["marketing_strategy_id"],
    )
    op.create_index("ix_copy_matrices_product_id", "copy_matrices", ["product_id"])

    op.create_table(
        "video_projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("marketing_strategy_id", sa.Integer(), nullable=False),
        sa.Column("copy_matrix_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("concept", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=20), nullable=False),
        sa.Column("scenes", sa.JSON(), nullable=False),
        sa.Column("cta", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["marketing_strategy_id"],
            ["marketing_strategies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["copy_matrix_id"], ["copy_matrices.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_video_projects_copy_matrix_id", "video_projects", ["copy_matrix_id"]
    )
    op.create_index(
        "ix_video_projects_marketing_strategy_id",
        "video_projects",
        ["marketing_strategy_id"],
    )
    op.create_index("ix_video_projects_product_id", "video_projects", ["product_id"])

    op.create_table(
        "demo_scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("fixture_version", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("marketing_strategy_id", sa.Integer(), nullable=False),
        sa.Column("copy_matrix_id", sa.Integer(), nullable=False),
        sa.Column("video_project_id", sa.Integer(), nullable=False),
        sa.Column("campaign_ids", sa.JSON(), nullable=False),
        sa.Column("growth_recommendation", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["marketing_strategy_id"],
            ["marketing_strategies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["copy_matrix_id"], ["copy_matrices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["video_project_id"], ["video_projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_demo_scenarios_product_id", "demo_scenarios", ["product_id"])

    op.create_table(
        "video_render_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_project_id", sa.Integer(), nullable=False),
        sa.Column("scene_sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=True),
        sa.Column("provider_task_id", sa.String(length=300), nullable=True),
        sa.Column("render_prompt", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=20), nullable=False),
        sa.Column("resolution", sa.String(length=50), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("error_code", sa.String(length=200), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["video_project_id"], ["video_projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_video_render_tasks_idempotency_key",
        "video_render_tasks",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_video_render_tasks_provider_task_id",
        "video_render_tasks",
        ["provider_task_id"],
    )
    op.create_index("ix_video_render_tasks_status", "video_render_tasks", ["status"])
    op.create_index(
        "ix_video_render_tasks_video_project_id",
        "video_render_tasks",
        ["video_project_id"],
    )

    op.create_table(
        "video_render_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_render_task_id", sa.Integer(), nullable=False),
        sa.Column("provider_output_url", sa.String(length=2000), nullable=True),
        sa.Column("storage_path", sa.String(length=2000), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["video_render_task_id"],
            ["video_render_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_video_render_artifacts_video_render_task_id",
        "video_render_artifacts",
        ["video_render_task_id"],
        unique=True,
    )

    op.create_table(
        "publish_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("social_account_id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("preflight_digest", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("privacy_status", sa.String(length=20), nullable=False),
        sa.Column("made_for_kids", sa.Boolean(), nullable=False),
        sa.Column("synthetic_media", sa.Boolean(), nullable=False),
        sa.Column("notify_subscribers", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider_video_id", sa.String(length=255), nullable=True),
        sa.Column("resumable_session_ciphertext", sa.Text(), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.Column("uncertain", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["social_account_id"], ["social_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["video_render_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_publish_task_idempotency"),
    )
    op.create_index("ix_publish_tasks_artifact_id", "publish_tasks", ["artifact_id"])
    op.create_index("ix_publish_tasks_product_id", "publish_tasks", ["product_id"])
    op.create_index(
        "ix_publish_tasks_provider_video_id",
        "publish_tasks",
        ["provider_video_id"],
    )
    op.create_index(
        "ix_publish_tasks_request_digest", "publish_tasks", ["request_digest"]
    )
    op.create_index(
        "ix_publish_tasks_social_account_id", "publish_tasks", ["social_account_id"]
    )
    op.create_index("ix_publish_tasks_status", "publish_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_publish_tasks_status", table_name="publish_tasks")
    op.drop_index("ix_publish_tasks_social_account_id", table_name="publish_tasks")
    op.drop_index("ix_publish_tasks_request_digest", table_name="publish_tasks")
    op.drop_index("ix_publish_tasks_provider_video_id", table_name="publish_tasks")
    op.drop_index("ix_publish_tasks_product_id", table_name="publish_tasks")
    op.drop_index("ix_publish_tasks_artifact_id", table_name="publish_tasks")
    op.drop_table("publish_tasks")
    op.drop_index(
        "ix_video_render_artifacts_video_render_task_id",
        table_name="video_render_artifacts",
    )
    op.drop_table("video_render_artifacts")
    op.drop_index(
        "ix_video_render_tasks_video_project_id", table_name="video_render_tasks"
    )
    op.drop_index("ix_video_render_tasks_status", table_name="video_render_tasks")
    op.drop_index(
        "ix_video_render_tasks_provider_task_id", table_name="video_render_tasks"
    )
    op.drop_index(
        "ix_video_render_tasks_idempotency_key", table_name="video_render_tasks"
    )
    op.drop_table("video_render_tasks")
    op.drop_index("ix_demo_scenarios_product_id", table_name="demo_scenarios")
    op.drop_table("demo_scenarios")
    op.drop_index("ix_video_projects_product_id", table_name="video_projects")
    op.drop_index(
        "ix_video_projects_marketing_strategy_id", table_name="video_projects"
    )
    op.drop_index("ix_video_projects_copy_matrix_id", table_name="video_projects")
    op.drop_table("video_projects")
    op.drop_index("ix_copy_matrices_product_id", table_name="copy_matrices")
    op.drop_index("ix_copy_matrices_marketing_strategy_id", table_name="copy_matrices")
    op.drop_table("copy_matrices")
    op.drop_index(
        "ix_social_accounts_provider_account_id", table_name="social_accounts"
    )
    op.drop_index("ix_social_accounts_product_id", table_name="social_accounts")
    op.drop_index("ix_social_accounts_platform", table_name="social_accounts")
    op.drop_index("ix_social_accounts_connection_status", table_name="social_accounts")
    op.drop_table("social_accounts")
    op.drop_index("ix_product_assets_product_id", table_name="product_assets")
    op.drop_table("product_assets")
    op.drop_index("ix_oauth_sessions_state_digest", table_name="oauth_sessions")
    op.drop_index("ix_oauth_sessions_product_id", table_name="oauth_sessions")
    op.drop_table("oauth_sessions")
    op.drop_index(
        "ix_marketing_strategies_product_id", table_name="marketing_strategies"
    )
    op.drop_table("marketing_strategies")
    op.drop_index("ix_marketing_briefs_product_id", table_name="marketing_briefs")
    op.drop_table("marketing_briefs")
    op.drop_index("ix_ad_campaigns_product_id", table_name="ad_campaigns")
    op.drop_index("ix_ad_campaigns_platform", table_name="ad_campaigns")
    op.drop_index("ix_ad_campaigns_date", table_name="ad_campaigns")
    op.drop_table("ad_campaigns")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_table("products")
