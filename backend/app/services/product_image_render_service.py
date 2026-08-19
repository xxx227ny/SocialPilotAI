from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import (
    ExecutionJob,
    ProductAsset,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.schemas.execution import ExecutionJobRead
from app.schemas.product_marketing_video import (
    JobSubmitRead,
    ProductImageRenderSubmitRequest,
)
from app.services.product_asset_storage import ProductAssetStorage
from app.services.product_image_ffmpeg import ProductImageFfmpeg
from app.services.video_artifact_storage import LocalVideoArtifactStorage

PRODUCT_IMAGE_RENDER_V1 = "video.product_image.render.v1"


class ProductImageRenderService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session, self.settings = session, settings

    def enqueue(
        self, product_id: int, data: ProductImageRenderSubmitRequest
    ) -> JobSubmitRead:
        if not self.settings.enable_real_product_video:
            raise AppError("Real product video execution is disabled", 503)
        project = self.session.get(VideoProject, data.video_project_id)
        asset = self.session.get(ProductAsset, data.product_asset_id)
        if (
            project is None
            or asset is None
            or project.product_id != product_id
            or asset.product_id != product_id
        ):
            raise AppError("Product image render source not found", 404)
        scene = next(
            (
                item
                for item in project.scenes
                if item["sequence"] == data.scene_sequence
            ),
            None,
        )
        if (
            scene is None
            or asset.sha256 != data.product_asset_sha256
            or scene.get("source_product_asset_id") != asset.id
            or scene.get("source_product_asset_sha256") != asset.sha256
            or scene.get("motion") != data.motion
        ):
            raise AppError("Product image render frozen input mismatch", 409)
        key = f"{PRODUCT_IMAGE_RENDER_V1}:{data.input_digest}:{data.scene_sequence}"
        existing_job = (
            self.session.query(ExecutionJob)
            .filter_by(idempotency_key=key)
            .one_or_none()
        )
        if existing_job is not None:
            if existing_job.input_digest != data.input_digest:
                raise AppError("Product image render idempotency conflict", 409)
            return JobSubmitRead(
                job=ExecutionJobRead.model_validate(existing_job), reused=True
            )
        task = VideoRenderTask(
            video_project_id=project.id,
            scene_sequence=data.scene_sequence,
            status="CREATED",
            provider_name="local_ffmpeg",
            render_prompt=f"Exact ProductAsset #{asset.id}; motion={data.motion}",
            duration_seconds=int(scene["duration_seconds"]),
            aspect_ratio="9:16",
            resolution="1080x1920",
            idempotency_key=key,
            source_product_asset_id=asset.id,
            source_product_asset_sha256=asset.sha256,
        )
        self.session.add(task)
        self.session.flush()
        job = ExecutionJob(
            job_type=PRODUCT_IMAGE_RENDER_V1,
            source_type="video_render_task",
            source_id=task.id,
            input_digest=data.input_digest,
            idempotency_key=key,
            input_payload={
                "task_id": task.id,
                "product_id": product_id,
                "asset_id": asset.id,
                "asset_sha256": asset.sha256,
                "motion": data.motion,
            },
            concurrency_key=f"product-image-render-{task.id}",
            estimated_cost=Decimal("0"),
            currency="USD",
            cost_confirmed=True,
            max_attempts=1,
            status="QUEUED",
        )
        self.session.add(job)
        self.session.commit()
        return JobSubmitRead(job=ExecutionJobRead.model_validate(job), reused=False)

    def render(
        self, task_id: int, asset_id: int, asset_sha256: str, motion: str
    ) -> VideoRenderArtifact:
        task = self.session.get(VideoRenderTask, task_id)
        asset = self.session.get(ProductAsset, asset_id)
        existing = (
            self.session.query(VideoRenderArtifact)
            .filter_by(video_render_task_id=task_id)
            .one_or_none()
        )
        if existing is not None:
            return existing
        if (
            task is None
            or asset is None
            or task.source_product_asset_id != asset.id
            or task.source_product_asset_sha256 != asset_sha256
            or asset.sha256 != asset_sha256
            or not asset.storage_identity
        ):
            raise AppError("Product image render identity mismatch", 409)
        source = ProductAssetStorage(
            Path(self.settings.product_asset_storage_root or ""),
            self.settings.product_asset_max_bytes,
            ffmpeg_path=self.settings.video_composition_ffmpeg_path,
            ffprobe_path=self.settings.video_composition_ffprobe_path,
            process_timeout=self.settings.video_composition_process_timeout,
        ).resolve(asset.storage_identity, asset_sha256)
        content = ProductImageFfmpeg(self.settings).render(
            source, task.duration_seconds, motion
        )
        stored = LocalVideoArtifactStorage(
            Path(self.settings.video_artifact_storage_root or ""),
            self.settings.video_artifact_max_bytes,
        ).store(task_id=task.id, content=content, content_type="video/mp4")
        artifact = VideoRenderArtifact(
            video_render_task_id=task.id,
            storage_path=stored.relative_path,
            artifact_metadata={
                "content_type": stored.content_type,
                "size_bytes": stored.size_bytes,
                "sha256": stored.sha256,
                "source_product_asset_id": asset.id,
                "source_product_asset_sha256": asset_sha256,
                "motion": motion,
            },
        )
        task.status = "SUCCEEDED"
        task.provider_name = "local_ffmpeg"
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        return artifact
