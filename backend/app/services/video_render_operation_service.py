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
from app.providers.visual_base import (
    VisualGenerationProvider,
    VisualGenerationRequest,
    VisualReferenceImage,
)
from app.repositories.video_render import VideoRenderTaskRepository
from app.repositories.video_render_artifact_repository import (
    VideoRenderArtifactRepository,
)
from app.schemas.video_render import (
    VideoRenderArtifactReferenceRead,
    VideoRenderArtifactSafeRead,
    VideoRenderOperationRead,
    VideoRenderRecoveryDecisionRead,
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
    WORKSPACE_RENDER_CONTRACT_VERSION,
    WORKSPACE_RENDER_PROVIDER,
    WORKSPACE_RENDER_RESOLUTION,
    WORKSPACE_RENDER_SCENE_SEQUENCE,
    VideoProjectQueryService,
    VideoRenderPreflightService,
)
from app.services.video_render_service import VideoRenderService

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
        self.preflight_service = VideoRenderPreflightService(session, app_settings)
        self.render_service = VideoRenderService(session)
        self.render_repository = VideoRenderTaskRepository(session)
        self.artifact_repository = VideoRenderArtifactRepository(session)
        self.recovery_service = VideoRenderRecoveryService(session, artifact_storage)

    async def execute(
        self,
        video_project_id: int,
        *,
        reference_image: VisualReferenceImage | None = None,
        reference_product_asset_id: int | None = None,
        reference_product_asset_sha256: str | None = None,
        whole_timeline: bool = False,
    ) -> VideoRenderOperationRead:
        self._require_execution_enabled()
        project = self.project_service.get(video_project_id)
        preflight = self.preflight_service.run(project.id)
        self._require_ready(preflight)

        if whole_timeline:
            if (
                reference_image is None
                or reference_product_asset_id is None
                or reference_product_asset_sha256 is None
            ):
                raise AppError("Product-reference video input is incomplete", 422)
            task, reused = self._create_product_reference_task(
                project,
                reference_product_asset_id,
                reference_product_asset_sha256,
            )
        else:
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
            return self.recovery_service.build_operation(
                project,
                task,
                artifact,
                reused=True,
                external_call=False,
            )

        try:
            request = None
            if whole_timeline and reference_image is not None:
                request = VisualGenerationRequest(
                    prompt=task.render_prompt,
                    duration_seconds=task.duration_seconds,
                    aspect_ratio=task.aspect_ratio,
                    resolution=task.resolution,
                    reference_images=(reference_image,),
                )
            result = await self._execution_service().submit(task.id, request)
        except AppError as exc:
            if exc.status_code == 409:
                recovered = self.render_service.get_render_task(task.id)
                artifact = self.artifact_repository.get_by_task_id(recovered.id)
                return self.recovery_service.build_operation(
                    project,
                    recovered,
                    artifact,
                    reused=True,
                    external_call=False,
                    recovered=True,
                )
            raise
        return self.recovery_service.build_operation(
            project,
            result.task,
            result.artifact,
            reused=reused,
            external_call=result.external_call,
        )

    def _create_product_reference_task(
        self,
        project: VideoProject,
        reference_product_asset_id: int,
        reference_product_asset_sha256: str,
    ) -> tuple[VideoRenderTask, bool]:
        stable_input = {
            "contract": "product-reference-i2v-v1",
            "video_project_id": project.id,
            "provider": WORKSPACE_RENDER_PROVIDER,
            "model": self.settings.wanx_i2v_model,
            "duration_seconds": project.duration_seconds,
            "aspect_ratio": project.aspect_ratio,
            "resolution": WORKSPACE_RENDER_RESOLUTION,
            "reference_product_asset_id": reference_product_asset_id,
            "reference_product_asset_sha256": reference_product_asset_sha256,
            "scenes": project.scenes,
        }
        digest = hashlib.sha256(
            json.dumps(
                stable_input,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        key = f"product-reference-i2v-v1:{digest}"
        existing = self.render_repository.get_by_idempotency_key(key)
        if existing is not None:
            if (
                existing.video_project_id != project.id
                or existing.source_product_asset_id != reference_product_asset_id
                or existing.source_product_asset_sha256
                != reference_product_asset_sha256
            ):
                raise AppError("Video render identity mismatch", 409)
            return existing, True
        scene_lines = []
        for scene in project.scenes:
            scene_lines.append(
                "{start}-{end}s: {visual}; physical action: {action}".format(
                    start=scene.get("start_ms", 0) / 1000,
                    end=scene.get("end_ms", 0) / 1000,
                    visual=scene.get("visual_description", ""),
                    action=scene.get("action_description", scene.get("action", "")),
                )
            )
        prompt = (
            "Create a realistic vertical product demonstration video using the exact "
            "product in the reference image. Show the physical product operating and "
            "demonstrate its benefits with natural hands, environment interaction, "
            "continuous camera motion and coherent multi-shot transitions. Preserve "
            "the product shape, materials, colors and branding. This must be real "
            "motion, not a slideshow, still-image pan, zoom animation, or floating "
            "product cutout. No subtitles, captions, logos, watermarks or audio. "
            "Timeline: " + " | ".join(scene_lines)
        )
        task = self.render_repository.create(
            video_project_id=project.id,
            scene_sequence=WORKSPACE_RENDER_SCENE_SEQUENCE,
            render_prompt=prompt,
            duration_seconds=project.duration_seconds,
            aspect_ratio=project.aspect_ratio,
            resolution=WORKSPACE_RENDER_RESOLUTION,
            idempotency_key=key,
            source_product_asset_id=reference_product_asset_id,
            source_product_asset_sha256=reference_product_asset_sha256,
        )
        return task, False

    def _execution_service(self) -> VideoRenderExecutionService:
        return VideoRenderExecutionService(
            self.session,
            self.provider,
            self.settings,
            output_fetcher=self.output_fetcher,
            artifact_storage=self.artifact_storage,
            provider_name="wanx",
            provider_label="Wanx",
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
        storage_configured = getattr(preflight, "artifact_storage_configured", False)
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

    def __init__(
        self,
        session: Session,
        artifact_storage: VideoArtifactStorage | None = None,
    ) -> None:
        self.project_service = VideoProjectQueryService(session)
        self.render_service = VideoRenderService(session)
        self.render_repository = VideoRenderTaskRepository(session)
        self.artifact_repository = VideoRenderArtifactRepository(session)
        self.artifact_access = (
            VideoArtifactAccessService(session, artifact_storage)
            if artifact_storage is not None
            else None
        )

    def get_latest(self, video_project_id: int) -> VideoRenderOperationRead:
        project = self.project_service.get(video_project_id)
        task = self.render_repository.get_latest_by_video_project(project.id)
        if task is None:
            raise AppError(
                "Video render task not found for VideoProject",
                status_code=404,
            )
        artifact = self.artifact_repository.get_by_task_id(task.id)
        return self.build_operation(
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
        return self.build_operation(
            project,
            task,
            artifact,
            reused=True,
            external_call=False,
            recovered=True,
        )

    def build_operation(
        self,
        project: VideoProject,
        task: VideoRenderTask,
        artifact: VideoRenderArtifact | None,
        *,
        reused: bool,
        external_call: bool,
        recovered: bool = False,
    ) -> VideoRenderOperationRead:
        return build_video_render_operation(
            project,
            task,
            artifact,
            reused=reused,
            external_call=external_call,
            recovered=recovered,
            artifact_state=self._artifact_state(task, artifact),
        )

    def _artifact_state(
        self,
        task: VideoRenderTask,
        artifact: VideoRenderArtifact | None,
    ) -> str:
        if task.status != "SUCCEEDED":
            return "not_applicable"
        if artifact is None:
            return "missing"
        if self.artifact_access is None:
            return "invalid"
        try:
            self.artifact_access.resolve_verified(artifact.id)
        except AppError as exc:
            return "missing" if exc.status_code == 404 else "invalid"
        return "available"


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
    artifact_state: str,
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
        recovery=build_recovery_decision(task, artifact_state),
        association_notice=VIDEO_PROJECT_ASSOCIATION_NOTICE,
    )


def build_recovery_decision(
    task: VideoRenderTask,
    artifact_state: str,
) -> VideoRenderRecoveryDecisionRead:
    status = task.status
    common = {
        "artifact_state": artifact_state,
        "read_only_retry_allowed": True,
        "presentation_fallback_available": True,
        "automatic_action_allowed": False,
    }
    provider_task_id_available = bool(
        task.provider_task_id and task.provider_task_id.strip()
    )
    if status == "CREATED" and provider_task_id_available:
        return VideoRenderRecoveryDecisionRead(
            category="submit_uncertain",
            continue_original_submit_allowed=False,
            explicit_refresh_allowed=False,
            resubmit_forbidden=True,
            user_message=(
                "原始RenderTask状态异常且Provider任务身份已存在；"
                "禁止继续提交，只能重新读取本地状态。"
            ),
            **common,
        )
    if status == "CREATED":
        return VideoRenderRecoveryDecisionRead(
            category="created",
            continue_original_submit_allowed=True,
            explicit_refresh_allowed=False,
            resubmit_forbidden=False,
            user_message=(
                "原始RenderTask尚未提交；仅可在双端执行开关和本次费用确认"
                "均有效时继续提交同一个任务。"
            ),
            **common,
        )
    if status in {"SUBMITTING", "SUBMIT_UNKNOWN"}:
        return VideoRenderRecoveryDecisionRead(
            category="submit_uncertain",
            continue_original_submit_allowed=False,
            explicit_refresh_allowed=False,
            resubmit_forbidden=True,
            user_message=(
                "Provider可能已经接收任务；禁止重新提交或自动刷新，"
                "只能重新读取本地状态。"
            ),
            **common,
        )
    if status in {"SUBMITTED", "PENDING", "RUNNING"} and (
        not provider_task_id_available
    ):
        return VideoRenderRecoveryDecisionRead(
            category="refresh_uncertain",
            continue_original_submit_allowed=False,
            explicit_refresh_allowed=False,
            resubmit_forbidden=True,
            user_message=(
                "任务状态显示正在处理，但缺少可安全核对的Provider任务身份；"
                "禁止刷新或重新提交，只能重新读取本地状态。"
            ),
            **common,
        )
    if status in {"SUBMITTED", "PENDING", "RUNNING"}:
        return VideoRenderRecoveryDecisionRead(
            category="active",
            continue_original_submit_allowed=False,
            explicit_refresh_allowed=True,
            resubmit_forbidden=True,
            user_message=(
                "任务正在处理中；只允许用户显式刷新一次Provider状态，不会后台轮询。"
            ),
            **common,
        )
    if status == "REFRESHING":
        return VideoRenderRecoveryDecisionRead(
            category="refresh_uncertain",
            continue_original_submit_allowed=False,
            explicit_refresh_allowed=False,
            resubmit_forbidden=True,
            user_message=("刷新结果尚不确定；禁止并发刷新，只能重新读取本地状态。"),
            **common,
        )
    if status in {"FAILED", "CANCELED"}:
        return VideoRenderRecoveryDecisionRead(
            category="terminal_failure",
            continue_original_submit_allowed=False,
            explicit_refresh_allowed=False,
            resubmit_forbidden=True,
            user_message=(
                "任务已进入失败或取消终态；本阶段不会重新提交旧任务或自动创建替代任务。"
            ),
            **common,
        )
    if status == "ARTIFACT_PERSIST_FAILED":
        return VideoRenderRecoveryDecisionRead(
            category="artifact_persist_failed",
            continue_original_submit_allowed=False,
            explicit_refresh_allowed=False,
            resubmit_forbidden=True,
            user_message=(
                "视频可能已由Provider生成，但本地持久化失败；"
                "不会访问旧Provider地址、重新下载或重新提交。"
            ),
            **common,
        )
    if status == "SUCCEEDED" and artifact_state == "available":
        return VideoRenderRecoveryDecisionRead(
            category="succeeded",
            continue_original_submit_allowed=False,
            explicit_refresh_allowed=False,
            resubmit_forbidden=True,
            user_message=("任务已成功，稳定本地Artifact可用于播放和下载。"),
            **common,
        )
    return VideoRenderRecoveryDecisionRead(
        category="succeeded_artifact_unavailable",
        continue_original_submit_allowed=False,
        explicit_refresh_allowed=False,
        resubmit_forbidden=True,
        user_message=(
            "RenderTask已成功，但本地视频当前不可用；不会回退到"
            "Provider URL、重新提交或自动刷新。"
        ),
        **common,
    )


def build_safe_artifact(
    resolved: VerifiedVideoArtifact,
) -> VideoRenderArtifactSafeRead:
    artifact = resolved.artifact
    return VideoRenderArtifactSafeRead(
        id=artifact.id,
        video_render_task_id=artifact.video_render_task_id,
        provider=artifact.video_render_task.provider_name or "unknown",
        content_url=(f"/api/v1/video-render-artifacts/{artifact.id}/content"),
        download_url=(f"/api/v1/video-render-artifacts/{artifact.id}/download"),
        content_type=resolved.content_type,
        size_bytes=resolved.size_bytes,
        sha256=resolved.sha256,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
    )
