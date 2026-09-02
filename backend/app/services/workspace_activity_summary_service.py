from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CopyMatrix,
    ExecutionJob,
    MarketingStrategy,
    Product,
    ProductAsset,
    ProviderCredential,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.schemas.dashboard import WorkspaceActivitySummarySchema
from app.services.provider_credential_service import DASHSCOPE_PROVIDER


class WorkspaceActivitySummaryService:
    """Aggregate only persisted records owned by one authenticated workspace."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, workspace_id: int) -> WorkspaceActivitySummarySchema:
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
        return WorkspaceActivitySummarySchema(
            api_key_configured=credential is not None,
            api_key_verified=(
                credential is not None and credential.verified_at is not None
            ),
            product_count=product_count,
            product_asset_count=product_asset_count,
            strategy_count=strategy_count,
            copy_matrix_count=copy_matrix_count,
            video_project_count=video_project_count,
            video_artifact_count=video_artifact_count,
            active_job_count=active_job_count,
            attention_job_count=attention_job_count,
        )

    def _count(self, statement) -> int:
        return int(self.db.scalar(statement) or 0)
