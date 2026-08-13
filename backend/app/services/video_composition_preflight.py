from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import Product, VideoProject, VideoRenderArtifact, VideoRenderTask
from app.schemas.video_composition import (
    FrozenCompositionShotRead,
    VideoCompositionPreflightRead,
    VideoCompositionPreflightRequest,
)
from app.services.video_artifact_storage import VideoArtifactStorage
from app.services.video_render_operation_service import VideoArtifactAccessService

PREFLIGHT_TTL = timedelta(minutes=10)
OUTPUT_CONTRACT = {
    "duration_ms": 15000,
    "container": "mp4",
    "video_codec": "h264",
    "profile": "high",
    "pixel_format": "yuv420p",
    "width": 1080,
    "height": 1920,
    "fps_numerator": 30,
    "fps_denominator": 1,
    "audio_codec": "aac",
    "audio_sample_rate": 48000,
    "audio_kind": "deterministic_silence_placeholder",
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


class VideoCompositionPreflightService:
    def __init__(self, session: Session, storage: VideoArtifactStorage) -> None:
        self.session = session
        self.access = VideoArtifactAccessService(session, storage)

    def run(
        self,
        product_id: int,
        data: VideoCompositionPreflightRequest,
        *,
        expires_at: datetime | None = None,
    ) -> VideoCompositionPreflightRead:
        product = self.session.get(Product, product_id)
        project = self.session.get(VideoProject, data.video_project_id)
        if product is None or project is None or project.product_id != product_id:
            raise AppError("VideoProject does not belong to Product", 404)
        frozen: list[FrozenCompositionShotRead] = []
        for requested in sorted(data.shots, key=lambda item: item.sequence):
            task = self.session.get(VideoRenderTask, requested.render_task_id)
            artifact = self.session.get(VideoRenderArtifact, requested.artifact_id)
            if (
                task is None
                or artifact is None
                or task.video_project_id != project.id
                or task.scene_sequence != requested.sequence
                or task.status != "SUCCEEDED"
                or artifact.video_render_task_id != task.id
            ):
                raise AppError("Composition shot source identity is invalid", 409)
            if requested.trim_end_ms > task.duration_seconds * 1000:
                raise AppError("Composition shot trim exceeds source duration", 409)
            verified = self.access.resolve_verified(artifact.id)
            if verified.content_type != "video/mp4":
                raise AppError("Composition source must be MP4", 409)
            frozen.append(
                FrozenCompositionShotRead(
                    **requested.model_dump(),
                    product_id=product_id,
                    video_project_id=project.id,
                    artifact_sha256=verified.sha256,
                )
            )
        source_material = [shot.model_dump(mode="json") for shot in frozen]
        source_chain_digest = _digest(source_material)
        input_digest = _digest(
            {
                "contract": "video-composition-render-v1",
                "product_id": product_id,
                "video_project_id": project.id,
                "source_chain_digest": source_chain_digest,
                "output": OUTPUT_CONTRACT,
            }
        )
        expiry = (expires_at or datetime.now(UTC) + PREFLIGHT_TTL).astimezone(UTC)
        preflight_digest = _digest(
            {"input_digest": input_digest, "expires_at": expiry.isoformat()}
        )
        return VideoCompositionPreflightRead(
            product_id=product_id,
            video_project_id=project.id,
            shots=frozen,
            input_digest=input_digest,
            source_chain_digest=source_chain_digest,
            preflight_digest=preflight_digest,
            expires_at=expiry,
            ready=True,
            missing_requirements=[],
            output_contract=OUTPUT_CONTRACT,
            execution_notice="Worker将使用本地CPU、临时磁盘和ffmpeg完成合成。",
            placeholder_audio_notice=(
                "Stage 3A 仅生成确定性静音 AAC 占位音轨，"
                "不是配音或背景音乐。"
            ),
        )
