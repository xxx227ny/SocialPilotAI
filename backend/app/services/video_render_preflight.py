from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import CopyMatrix, MarketingStrategy, Product, VideoProject
from app.providers.live_configuration import (
    wanx_missing_requirements,
    wanx_provider_configured,
)
from app.providers.wanx_provider import WANX_RATIOS
from app.repositories.product import ProductRepository
from app.repositories.video import VideoProjectRepository
from app.schemas.video import VideoPlanSchema, VideoProjectSchema, VideoSceneSchema
from app.schemas.video_render import VideoRenderPreflightRead

VIDEO_RENDER_COST_NOTICE = (
    "真实视频生成可能消耗阿里云百炼额度，具体消耗以平台实际计费为准。"
)
VIDEO_PROJECT_ASSOCIATION_NOTICE = (
    "当前VideoProject持久化关联Product、MarketingStrategy和CopyMatrix；"
    "没有MarketingBrief外键，不能声明与MarketingBrief存在持久化关联。"
)
VIDEO_RENDER_CONTRACT_CAPABILITIES = {
    "exact_video_project_render_task_execution_contract",
    "uncertain_submit_recovery_contract",
    "durable_video_artifact_storage_contract",
}


class VideoProjectQueryService:
    """Read exact or Product-scoped VideoProjects without Provider interaction."""

    def __init__(self, session: Session) -> None:
        self.product_repository = ProductRepository(session)
        self.video_repository = VideoProjectRepository(session)

    def get(self, video_project_id: int) -> VideoProject:
        project = self.video_repository.get(video_project_id)
        if project is None:
            raise AppError("Video project not found", status_code=404)
        return project

    def get_latest_for_product(self, product_id: int) -> VideoProject:
        if self.product_repository.get(product_id) is None:
            raise AppError("Product not found", status_code=404)
        project = self.video_repository.get_latest_by_product(product_id)
        if project is None:
            raise AppError(
                "Video project not found for Product",
                status_code=404,
            )
        if project.product_id != product_id:
            raise AppError(
                "Video project does not belong to Product",
                status_code=409,
            )
        return project


class VideoRenderPreflightService:
    """Validate one exact VideoProject without constructing a Provider request."""

    def __init__(self, session: Session, app_settings: Settings) -> None:
        self.session = session
        self.settings = app_settings
        self.video_repository = VideoProjectRepository(session)

    def run(self, video_project_id: int) -> VideoRenderPreflightRead:
        project = self.video_repository.get(video_project_id)
        if project is None:
            raise AppError("Video project not found", status_code=404)

        product = self.session.get(Product, project.product_id)
        if product is None:
            raise AppError("Video project Product not found", status_code=404)
        if project.product_id != product.id:
            raise AppError(
                "Video project does not belong to Product",
                status_code=409,
            )

        missing = self._input_requirements(project, product)
        input_ready = not missing
        provider_configured = self._provider_configured()
        if not provider_configured:
            missing.append("provider_configuration")
            missing.extend(wanx_missing_requirements(self.settings))
        if not self.settings.enable_video_render_execution:
            missing.append("video_render_execution")
        artifact_storage_configured = self._artifact_storage_configured()
        if not artifact_storage_configured:
            missing.append("artifact_storage_configuration")

        missing_contracts = self._missing_contract_requirements()
        missing.extend(missing_contracts)
        contract_ready = not missing_contracts
        ready_for_execution = all(
            (
                input_ready,
                provider_configured,
                self.settings.enable_video_render_execution,
                artifact_storage_configured,
                contract_ready,
            )
        )
        return VideoRenderPreflightRead(
            video_project_id=project.id,
            product_id=product.id,
            marketing_strategy_id=project.marketing_strategy_id,
            copy_matrix_id=project.copy_matrix_id,
            input_ready=input_ready,
            provider_configured=provider_configured,
            execution_enabled=self.settings.enable_video_render_execution,
            artifact_storage_configured=artifact_storage_configured,
            contract_ready=contract_ready,
            ready_for_execution=ready_for_execution,
            missing_requirements=missing,
            platform=project.platform or "",
            duration_seconds=project.duration_seconds,
            aspect_ratio=project.aspect_ratio or "",
            scene_count=len(project.scenes) if isinstance(project.scenes, list) else 0,
            project_status=project.status or "",
            estimated_cost_notice=VIDEO_RENDER_COST_NOTICE,
            association_notice=VIDEO_PROJECT_ASSOCIATION_NOTICE,
        )

    def _input_requirements(
        self, project: VideoProject, product: Product
    ) -> list[str]:
        missing: list[str] = []
        required_text = {
            "platform": project.platform,
            "title": project.title,
            "concept": project.concept,
            "aspect_ratio": project.aspect_ratio,
            "cta": project.cta,
            "project_status": project.status,
        }
        for name, value in required_text.items():
            if not isinstance(value, str) or not value.strip():
                missing.append(name)
        if project.duration_seconds <= 0:
            missing.append("duration_seconds")
        if not isinstance(project.scenes, list) or not project.scenes:
            missing.append("scenes")
        else:
            for index, scene in enumerate(project.scenes, start=1):
                try:
                    VideoSceneSchema.model_validate(scene)
                except ValidationError:
                    missing.append(f"scene_{index}_schema")
            first_scene = next(
                (
                    scene
                    for scene in project.scenes
                    if isinstance(scene, dict) and scene.get("sequence") == 1
                ),
                None,
            )
            first_duration = (
                first_scene.get("duration_seconds")
                if first_scene is not None
                else None
            )
            if (
                not isinstance(first_duration, int)
                or isinstance(first_duration, bool)
                or first_duration < 2
                or first_duration > 15
            ):
                missing.append("wanx_scene_duration")
        if project.aspect_ratio not in WANX_RATIOS:
            missing.append("wanx_aspect_ratio")

        strategy = self.session.get(
            MarketingStrategy, project.marketing_strategy_id
        )
        if strategy is None or strategy.product_id != product.id:
            missing.append("marketing_strategy_association")
        copy_matrix = self.session.get(CopyMatrix, project.copy_matrix_id)
        if (
            copy_matrix is None
            or copy_matrix.product_id != product.id
            or copy_matrix.marketing_strategy_id
            != project.marketing_strategy_id
        ):
            missing.append("copy_matrix_association")

        try:
            VideoPlanSchema.model_validate(
                {
                    "title": project.title,
                    "concept": project.concept,
                    "platform": project.platform,
                    "duration_seconds": project.duration_seconds,
                    "aspect_ratio": project.aspect_ratio,
                    "scenes": project.scenes,
                    "cta": project.cta,
                }
            )
            VideoProjectSchema.model_validate(project)
        except ValidationError:
            if "video_project_schema" not in missing:
                missing.append("video_project_schema")
        return missing

    def _provider_configured(self) -> bool:
        return wanx_provider_configured(self.settings)

    def _artifact_storage_configured(self) -> bool:
        configured = (self.settings.video_artifact_storage_root or "").strip()
        return bool(configured and Path(configured).is_absolute())

    @staticmethod
    def _missing_contract_requirements() -> list[str]:
        implemented = {
            "exact_video_project_render_task_execution_contract",
            "uncertain_submit_recovery_contract",
            "durable_video_artifact_storage_contract",
        }
        return sorted(VIDEO_RENDER_CONTRACT_CAPABILITIES - implemented)
