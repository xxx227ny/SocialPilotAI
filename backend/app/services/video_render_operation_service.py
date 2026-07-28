from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import VideoProject, VideoRenderArtifact, VideoRenderTask
from app.providers.visual_base import VisualGenerationProvider
from app.repositories.video_render import VideoRenderTaskRepository
from app.repositories.video_render_artifact_repository import (
    VideoRenderArtifactRepository,
)
from app.schemas.video_render import (
    VideoRenderArtifactReferenceRead,
    VideoRenderArtifactSafeRead,
    VideoRenderOperationRead,
    VideoRenderTaskCreate,
    VideoRenderTaskSafeRead,
)
from app.services.video_artifact_storage import (
    ProviderOutputFetcher,
    VideoArtifactError,
    VideoArtifactStorage,
)
from app.services.video_render_execution_service import (
    VideoRenderExecutionService,
)
from app.services.video_render_preflight import (
    VIDEO_PROJECT_ASSOCIATION_NOTICE,
    VideoProjectQueryService,
    VideoRenderPreflightService,
)
from app.services.video_render_service import VideoRenderService

WORKSPACE_RENDER_SCENE_SEQUENCE = 1
WORKSPACE_RENDER_RESOLUTION = "720P"
WORKSPACE_RENDER_CONTRACT_VERSION = "v1"
WORKSPACE_RENDER_PROVIDER = "wanx"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class VerifiedVideoArtifact:
    artifact: VideoRenderArtifact
    path: Path
    content_type: str
    size_bytes: int
    sha256: str


class VideoProjectRenderExecutionService:
    """Execute one exact persisted VideoProject scene with durable recovery."""

    def __init__(
        self,
        session: Session,
        provider: VisualGenerationProvider,
        app_settings: Settings,
        output_fetcher: ProviderOutputFetcher,
        artifact_storage: VideoArtifactStorage,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = app_settings
        self.output_fetcher = output_fetcher
        self.artifact_storage = artifact_storage
        self.project_service = VideoProjectQueryService(session)
        self.preflight_service = VideoRenderPreflightService(
            session, app_settings
        )
        self.render_service = VideoRenderService(session)
        self.render_repository = VideoRenderTaskRepository(session)
        self.artifact_repository = VideoRenderArtifactRepository(session)

    async def execute(
        self, video_project_id: int
    ) -> VideoRenderOperationRead:
        self._require_execution_enabled()
        project = self.project_service.get(video_project_id)
        preflight = self.preflight_service.run(project.id)
        self._require_ready(preflight)

        idempotency_key = self._idempotency_key(project)
        task, reused = self.render_service.create_render_task_with_reuse(
            project.id,
            VideoRenderTaskCreate(
                scene_sequence=WORKSPACE_RENDER_SCENE_SEQUENCE,
                resolution=WORKSPACE_RENDER_RESOLUTION,
                idempotency_key=idempotency_key,
            ),
        )
        if task.status != "CREATED" or task.provider_task_id is not None:
            artifact = self.artifact_repository.get_by_task_id(task.id)
            return build_video_render_operation(
                project,
                task,
                artifact,
                reused=True,
                external_call=False,
            )

        try:
            result = await self._execution_service().submit(task.id)
        except AppError as exc:
            if exc.status_code == 409:
                recovered = self.render_service.get_render_task(task.id)
                artifact = self.artifact_repository.get_by_task_id(
                    recovered.id
                )
                return build_video_render_operation(
                    project,
                    recovered,
                    artifact,
                    reused=True,
                    external_call=False,
                    recovered=True,
                )
            raise
        return build_video_render_operation(
            project,
            result.task,
            result.artifact,
            reused=reused,
            external_call=result.external_call,
        )

    def _execution_service(self) -> VideoRenderExecutionService:
        return VideoRenderExecutionService(
            self.session,
            self.provider,
            self.settings,
            output_fetcher=self.output_fetcher,
            artifact_storage=self.artifact_storage,
        )

    def _require_execution_enabled(self) -> None:
        if not self.settings.enable_video_render_execution:
            raise AppError(
                "Video render execution is disabled by the server",
                status_code=503,
            )

    @staticmethod
    def _require_ready(preflight: object) -> None:
        input_ready = getattr(preflight, "input_ready", False)
        provider_configured = getattr(preflight, "provider_configured", False)
        storage_configured = getattr(
            preflight, "artifact_storage_configured", False
        )
        contract_ready = getattr(preflight, "contract_ready", False)
        ready = getattr(preflight, "ready_for_execution", False)
        if not input_ready:
            raise AppError("VideoProject input is not ready", 422)
        if not provider_configured:
            raise AppError("Wanx provider is not configured", 503)
        if not storage_configured:
            raise AppError("Artifact storage is not configured", 503)
        if not contract_ready or not ready:
            raise AppError("Video render execution contract is not ready", 409)

    def _idempotency_key(self, project: VideoProject) -> str:
        scene = next(
            (
                item
                for item in project.scenes
                if item.get("sequence") == WORKSPACE_RENDER_SCENE_SEQUENCE
            ),
            None,
        )
        if scene is None:
            raise AppError("VideoProject first scene is missing", 422)
        stable_input = {
            "contract": WORKSPACE_RENDER_CONTRACT_VERSION,
            "video_project_id": project.id,
            "scene_sequence": WORKSPACE_RENDER_SCENE_SEQUENCE,
            "provider": WORKSPACE_RENDER_PROVIDER,
            "model": self.settings.wanx_model,
            "duration_seconds": scene.get("duration_seconds"),
            "aspect_ratio": project.aspect_ratio,
            "resolution": WORKSPACE_RENDER_RESOLUTION,
            "scene": scene,
        }
        serialized = json.dumps(
            stable_input,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return f"workspace-render:{WORKSPACE_RENDER_CONTRACT_VERSION}:{digest}"


class VideoRenderRecoveryService:
    """Read exact or latest Task/Artifact state without provider side effects."""

    def __init__(self, session: Session) -> None:
        self.project_service = VideoProjectQueryService(session)
        self.render_service = VideoRenderService(session)
        self.render_repository = VideoRenderTaskRepository(session)
        self.artifact_repository = VideoRenderArtifactRepository(session)

    def get_latest(self, video_project_id: int) -> VideoRenderOperationRead:
        project = self.project_service.get(video_project_id)
        task = self.render_repository.get_latest_by_video_project(project.id)
        if task is None:
            raise AppError(
                "Video render task not found for VideoProject",
                status_code=404,
            )
        artifact = self.artifact_repository.get_by_task_id(task.id)
        return build_video_render_operation(
            project,
            task,
            artifact,
            reused=True,
            external_call=False,
            recovered=True,
        )

    def get_task(self, task_id: int) -> VideoRenderOperationRead:
        task = self.render_service.get_render_task(task_id)
        project = self.project_service.get(task.video_project_id)
        artifact = self.artifact_repository.get_by_task_id(task.id)
        return build_video_render_operation(
            project,
            task,
            artifact,
            reused=True,
            external_call=False,
            recovered=True,
        )


class VideoArtifactAccessService:
    def __init__(
        self,
        session: Session,
        storage: VideoArtifactStorage,
    ) -> None:
        self.artifact_repository = VideoRenderArtifactRepository(session)
        self.storage = storage

    def get_metadata(self, artifact_id: int) -> VideoRenderArtifactSafeRead:
        return build_safe_artifact(self.resolve_verified(artifact_id))

    def resolve_verified(self, artifact_id: int) -> VerifiedVideoArtifact:
        artifact = self._get(artifact_id)
        if artifact.storage_path is None:
            raise AppError(
                "Stable video artifact is unavailable",
                status_code=409,
            )
        try:
            path, resolved_type = self.storage.resolve(artifact.storage_path)
        except VideoArtifactError as exc:
            raise AppError(exc.safe_message, 404) from exc

        metadata = artifact.artifact_metadata
        content_type = metadata.get("content_type")
        size_bytes = metadata.get("size_bytes")
        sha256 = metadata.get("sha256")
        if (
            not isinstance(content_type, str)
            or content_type != resolved_type
            or not isinstance(size_bytes, int)
            or size_bytes < 1
            or path.stat().st_size != size_bytes
            or not isinstance(sha256, str)
            or SHA256_PATTERN.fullmatch(sha256.lower()) is None
        ):
            raise AppError(
                "Stable video artifact integrity metadata is invalid",
                status_code=409,
            )
        return VerifiedVideoArtifact(
            artifact=artifact,
            path=path,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256.lower(),
        )

    def _get(self, artifact_id: int) -> VideoRenderArtifact:
        artifact = self.artifact_repository.get(artifact_id)
        if artifact is None:
            raise AppError("Video render artifact not found", status_code=404)
        task = artifact.video_render_task
        if task is None or task.status != "SUCCEEDED":
            raise AppError(
                "Video render artifact is not available",
                status_code=409,
            )
        return artifact


def build_video_render_operation(
    project: VideoProject,
    task: VideoRenderTask,
    artifact: VideoRenderArtifact | None,
    *,
    reused: bool,
    external_call: bool,
    recovered: bool = False,
) -> VideoRenderOperationRead:
    return VideoRenderOperationRead(
        video_project_id=project.id,
        product_id=project.product_id,
        marketing_strategy_id=project.marketing_strategy_id,
        copy_matrix_id=project.copy_matrix_id,
        task=VideoRenderTaskSafeRead.model_validate(task),
        artifact=(
            VideoRenderArtifactReferenceRead.model_validate(artifact)
            if artifact is not None
            else None
        ),
        reused=reused,
        external_call=external_call,
        recovered=recovered,
        association_notice=VIDEO_PROJECT_ASSOCIATION_NOTICE,
    )


def build_safe_artifact(
    resolved: VerifiedVideoArtifact,
) -> VideoRenderArtifactSafeRead:
    artifact = resolved.artifact
    return VideoRenderArtifactSafeRead(
        id=artifact.id,
        video_render_task_id=artifact.video_render_task_id,
        provider=artifact.video_render_task.provider_name or "unknown",
        content_url=(
            f"/api/v1/video-render-artifacts/{artifact.id}/content"
        ),
        download_url=(
            f"/api/v1/video-render-artifacts/{artifact.id}/download"
        ),
        content_type=resolved.content_type,
        size_bytes=resolved.size_bytes,
        sha256=resolved.sha256,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
    )
