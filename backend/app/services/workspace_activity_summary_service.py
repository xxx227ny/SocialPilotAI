from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    CopyMatrix,
    ExecutionAttempt,
    ExecutionJob,
    MarketingStrategy,
    Product,
    ProductAsset,
    ProviderCredential,
    PublishTask,
    SocialAccount,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.schemas.dashboard import (
    WorkspaceActivitySummarySchema,
    WorkspaceEstimatedCostSchema,
    WorkspaceSocialAccountCountSchema,
)
from app.services.provider_credential_service import DASHSCOPE_PROVIDER


class WorkspaceActivitySummaryService:
    """Aggregate only persisted records owned by one authenticated workspace."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(
        self,
        workspace_id: int,
        *,
        product_asset_storage_limit_bytes: int,
    ) -> WorkspaceActivitySummarySchema:
        credential = self.db.scalar(
            select(ProviderCredential).where(
                ProviderCredential.workspace_id == workspace_id,
                ProviderCredential.provider == DASHSCOPE_PROVIDER,
                ProviderCredential.status == "ACTIVE",
            )
        )
        product_count = self._count(
            select(func.count(Product.id)).where(Product.workspace_id == workspace_id)
        )
        product_asset_count = self._count(
            select(func.count(ProductAsset.id))
            .join(Product, Product.id == ProductAsset.product_id)
            .where(Product.workspace_id == workspace_id)
        )
        product_asset_storage_bytes = self._count(
            select(func.coalesce(func.sum(ProductAsset.size_bytes), 0))
            .join(Product, Product.id == ProductAsset.product_id)
            .where(Product.workspace_id == workspace_id)
        )
        strategy_count = self._count(
            select(func.count(MarketingStrategy.id))
            .join(Product, Product.id == MarketingStrategy.product_id)
            .where(Product.workspace_id == workspace_id)
        )
        copy_matrix_count = self._count(
            select(func.count(CopyMatrix.id))
            .join(Product, Product.id == CopyMatrix.product_id)
            .where(Product.workspace_id == workspace_id)
        )
        video_project_count = self._count(
            select(func.count(VideoProject.id))
            .join(Product, Product.id == VideoProject.product_id)
            .where(Product.workspace_id == workspace_id)
        )
        video_artifact_count = self._count(
            select(func.count(VideoRenderArtifact.id))
            .join(
                VideoRenderTask,
                VideoRenderTask.id == VideoRenderArtifact.video_render_task_id,
            )
            .join(VideoProject, VideoProject.id == VideoRenderTask.video_project_id)
            .join(Product, Product.id == VideoProject.product_id)
            .where(Product.workspace_id == workspace_id)
        )
        social_account_rows = self.db.execute(
            select(SocialAccount.platform, func.count(SocialAccount.id))
            .where(
                SocialAccount.workspace_id == workspace_id,
                SocialAccount.connection_status == "CONNECTED",
            )
            .group_by(SocialAccount.platform)
            .order_by(SocialAccount.platform)
        ).all()
        connected_social_accounts = [
            WorkspaceSocialAccountCountSchema(platform=platform, count=int(count))
            for platform, count in social_account_rows
        ]
        publish_task_count = self._count(
            select(func.count(PublishTask.id)).where(
                PublishTask.workspace_id == workspace_id
            )
        )
        successful_publish_count = self._count(
            select(func.count(PublishTask.id)).where(
                PublishTask.workspace_id == workspace_id,
                PublishTask.status == "SUCCEEDED",
            )
        )
        publish_attention_count = self._count(
            select(func.count(PublishTask.id)).where(
                PublishTask.workspace_id == workspace_id,
                PublishTask.status.in_(("FAILED", "SUBMIT_UNKNOWN")),
            )
        )
        active_job_count = self._count(
            select(func.count(ExecutionJob.id)).where(
                ExecutionJob.workspace_id == workspace_id,
                ExecutionJob.status.in_(("QUEUED", "RUNNING", "PAUSED")),
            )
        )
        attention_job_count = self._count(
            select(func.count(ExecutionJob.id)).where(
                ExecutionJob.workspace_id == workspace_id,
                ExecutionJob.status.in_(("FAILED", "SUBMIT_UNKNOWN")),
            )
        )
        ai_job_filter = or_(
            ExecutionJob.job_type.like("qwen.%"),
            ExecutionJob.job_type.like("wanx.%"),
            ExecutionJob.job_type.like("tts.%"),
            ExecutionJob.job_type.like("happyhorse.%"),
        )
        ai_job_count = self._count(
            select(func.count(ExecutionJob.id)).where(
                ExecutionJob.workspace_id == workspace_id,
                ai_job_filter,
            )
        )
        ai_success_count = self._count(
            select(func.count(ExecutionJob.id)).where(
                ExecutionJob.workspace_id == workspace_id,
                ai_job_filter,
                ExecutionJob.status == "SUCCEEDED",
            )
        )
        ai_attention_count = self._count(
            select(func.count(ExecutionJob.id)).where(
                ExecutionJob.workspace_id == workspace_id,
                ai_job_filter,
                ExecutionJob.status.in_(("FAILED", "SUBMIT_UNKNOWN")),
            )
        )
        ai_calls = self._count(
            select(func.coalesce(func.sum(ExecutionAttempt.provider_call_count), 0))
            .join(
                ExecutionJob,
                ExecutionJob.id == ExecutionAttempt.execution_job_id,
            )
            .where(
                ExecutionJob.workspace_id == workspace_id,
                ai_job_filter,
            )
        )
        estimated_cost_rows = self.db.execute(
            select(
                ExecutionJob.currency,
                func.coalesce(func.sum(ExecutionJob.estimated_cost), 0),
            )
            .where(
                ExecutionJob.workspace_id == workspace_id,
                ai_job_filter,
                ExecutionJob.cost_confirmed.is_(True),
                ExecutionJob.estimated_cost > 0,
            )
            .group_by(ExecutionJob.currency)
            .order_by(ExecutionJob.currency)
        ).all()
        return WorkspaceActivitySummarySchema(
            ai_calls=ai_calls,
            ai_job_count=ai_job_count,
            ai_success_count=ai_success_count,
            ai_attention_count=ai_attention_count,
            confirmed_estimated_costs=[
                WorkspaceEstimatedCostSchema(currency=currency, amount=amount)
                for currency, amount in estimated_cost_rows
            ],
            api_key_configured=credential is not None,
            api_key_verified=(
                credential is not None and credential.verified_at is not None
            ),
            product_count=product_count,
            product_asset_count=product_asset_count,
            product_asset_storage_bytes=product_asset_storage_bytes,
            product_asset_storage_limit_bytes=product_asset_storage_limit_bytes,
            strategy_count=strategy_count,
            copy_matrix_count=copy_matrix_count,
            video_project_count=video_project_count,
            video_artifact_count=video_artifact_count,
            connected_social_account_count=sum(
                item.count for item in connected_social_accounts
            ),
            connected_social_accounts=connected_social_accounts,
            publish_task_count=publish_task_count,
            successful_publish_count=successful_publish_count,
            publish_attention_count=publish_attention_count,
            active_job_count=active_job_count,
            attention_job_count=attention_job_count,
        )

    def _count(self, statement) -> int:
        return int(self.db.scalar(statement) or 0)
