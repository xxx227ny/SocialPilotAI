from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    ProductVideoProductionBatch,
    ProductVideoProductionItem,
    VideoCompositionEnhancementArtifact,
    VideoProject,
    VideoRenderArtifact,
    VideoScriptVersion,
)
from app.services.video_artifact_storage import VideoArtifactStorage
from app.services.video_composition_enhancement_service import (
    VideoCompositionEnhancementArtifactAccessService,
)
from app.services.video_render_operation_service import VideoArtifactAccessService

PROJECT_PLATFORM = {
    "youtube": "YouTube Shorts",
    "instagram": "Instagram Reels",
}


@dataclass(frozen=True, slots=True)
class VerifiedSocialPublishSource:
    artifact: VideoRenderArtifact
    final_artifact: VideoCompositionEnhancementArtifact | None
    production_item: ProductVideoProductionItem | None
    script_version: VideoScriptVersion | None
    project: VideoProject
    path: Path
    content_type: str
    size_bytes: int
    sha256: str

    @property
    def final_video_artifact_id(self) -> int | None:
        return self.final_artifact.id if self.final_artifact is not None else None


class SocialPublishSourceService:
    """Resolve either a legacy scene render or the pinned completed production file."""

    def __init__(
        self,
        session: Session,
        settings,
        render_storage: VideoArtifactStorage,
    ) -> None:
        self.session = session
        self.settings = settings
        self.render_access = VideoArtifactAccessService(session, render_storage)
        self._final_access: VideoCompositionEnhancementArtifactAccessService | None = (
            None
        )

    @property
    def final_access(self) -> VideoCompositionEnhancementArtifactAccessService:
        if self._final_access is None:
            self._final_access = VideoCompositionEnhancementArtifactAccessService(
                self.session, self.settings
            )
        return self._final_access

    def resolve(
        self,
        *,
        product_id: int,
        platform: str,
        artifact_id: int,
        final_video_artifact_id: int | None,
    ) -> VerifiedSocialPublishSource:
        expected_project_platform = PROJECT_PLATFORM.get(platform)
        if expected_project_platform is None:
            raise AppError("Social publishing platform is not supported", 409)
        verified_render = self.render_access.resolve_verified(artifact_id)
        task = verified_render.artifact.video_render_task
        project = task.video_project if task is not None else None
        if (
            project is None
            or project.product_id != product_id
            or project.platform != expected_project_platform
        ):
            raise AppError("Artifact does not belong to the requested platform", 409)
        if final_video_artifact_id is None:
            return VerifiedSocialPublishSource(
                artifact=verified_render.artifact,
                final_artifact=None,
                production_item=None,
                script_version=None,
                project=project,
                path=verified_render.path,
                content_type=verified_render.content_type,
                size_bytes=verified_render.size_bytes,
                sha256=verified_render.sha256,
            )

        item = self.session.scalar(
            select(ProductVideoProductionItem)
            .join(ProductVideoProductionBatch)
            .where(
                ProductVideoProductionBatch.product_id == product_id,
                ProductVideoProductionItem.platform == platform,
                ProductVideoProductionItem.status == "SUCCEEDED",
                ProductVideoProductionItem.stage == "COMPLETE",
                ProductVideoProductionItem.cloud_render_artifact_id == artifact_id,
                ProductVideoProductionItem.final_video_artifact_id
                == final_video_artifact_id,
            )
        )
        if (
            item is None
            or item.video_project_id != project.id
            or item.enhancement_id is None
            or item.script_version_id is None
        ):
            raise AppError("Completed production identity is invalid", 409)
        final_artifact, final_path = self.final_access.resolve_video(
            final_video_artifact_id
        )
        if (
            final_artifact.enhancement_id != item.enhancement_id
            or final_artifact.enhancement.product_id != product_id
            or final_artifact.enhancement.video_project_id != project.id
            or final_artifact.content_type != "video/mp4"
        ):
            raise AppError("Completed production chain is invalid", 409)
        script = self.session.get(VideoScriptVersion, item.script_version_id)
        if (
            script is None
            or script.product_id != product_id
            or script.platform != platform
            or script.batch_video_variant_id != item.batch_video_variant_id
        ):
            raise AppError("Completed production script identity is invalid", 409)
        return VerifiedSocialPublishSource(
            artifact=verified_render.artifact,
            final_artifact=final_artifact,
            production_item=item,
            script_version=script,
            project=project,
            path=final_path,
            content_type=final_artifact.content_type,
            size_bytes=final_artifact.size_bytes,
            sha256=final_artifact.sha256,
        )

    def latest_final(
        self, *, product_id: int, platform: str
    ) -> VerifiedSocialPublishSource:
        item = self.session.scalar(
            select(ProductVideoProductionItem)
            .join(ProductVideoProductionBatch)
            .where(
                ProductVideoProductionBatch.product_id == product_id,
                ProductVideoProductionItem.platform == platform,
                ProductVideoProductionItem.status == "SUCCEEDED",
                ProductVideoProductionItem.stage == "COMPLETE",
                ProductVideoProductionItem.cloud_render_artifact_id.is_not(None),
                ProductVideoProductionItem.final_video_artifact_id.is_not(None),
            )
            .order_by(
                ProductVideoProductionItem.completed_at.desc(),
                ProductVideoProductionItem.id.desc(),
            )
            .limit(1)
        )
        if (
            item is None
            or item.cloud_render_artifact_id is None
            or item.final_video_artifact_id is None
        ):
            raise AppError("No completed final video is available for publishing", 409)
        return self.resolve(
            product_id=product_id,
            platform=platform,
            artifact_id=item.cloud_render_artifact_id,
            final_video_artifact_id=item.final_video_artifact_id,
        )
