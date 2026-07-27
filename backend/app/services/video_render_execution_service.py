from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.exceptions import AppError
from app.models import VideoRenderArtifact, VideoRenderTask
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderError,
    ProviderModelError,
    ProviderQuotaError,
    ProviderTimeoutError,
)
from app.providers.visual_base import (
    VisualGenerationProvider,
    VisualGenerationRequest,
    VisualTaskSubmission,
)
from app.repositories.video_render import VideoRenderTaskRepository
from app.repositories.video_render_artifact_repository import (
    VideoRenderArtifactRepository,
)
from app.schemas.video_render_artifact import VideoRenderArtifactCreate
from app.services.video_artifact_storage import (
    ProviderOutputFetcher,
    VideoArtifactError,
    VideoArtifactStorage,
)
from app.services.video_render_service import VideoRenderService

REFRESHABLE_STATUSES = {"SUBMITTED", "PENDING", "RUNNING"}
NO_REFRESH_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED"}


@dataclass(frozen=True, slots=True)
class VideoRenderExecutionResult:
    task: VideoRenderTask
    artifact: VideoRenderArtifact | None
    external_call: bool


class VideoRenderExecutionService:
    """Orchestrate provider calls and synchronize local render state."""

    def __init__(
        self,
        session: Session,
        provider: VisualGenerationProvider,
        app_settings: Settings = settings,
        *,
        allow_live_demo: bool = False,
        output_fetcher: ProviderOutputFetcher | None = None,
        artifact_storage: VideoArtifactStorage | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.render_service = VideoRenderService(session)
        self.render_repository = VideoRenderTaskRepository(session)
        self.artifact_repository = VideoRenderArtifactRepository(session)
        self.settings = app_settings
        self.allow_live_demo = allow_live_demo
        self.output_fetcher = output_fetcher
        self.artifact_storage = artifact_storage

    async def submit(self, task_id: int) -> VideoRenderExecutionResult:
        self._require_execution_enabled()
        task = self.render_service.get_render_task(task_id)
        if task.status != "CREATED" or task.provider_task_id is not None:
            raise AppError("Video render task has already been submitted", 409)

        claimed = self.render_repository.claim_for_submission(task.id)
        if claimed is None:
            raise AppError("Video render task has already been submitted", 409)

        request = VisualGenerationRequest(
            prompt=claimed.render_prompt,
            duration_seconds=claimed.duration_seconds,
            aspect_ratio=claimed.aspect_ratio,
            resolution=claimed.resolution,
        )
        try:
            submission = await self.provider.submit(request)
        except (ProviderTimeoutError, ProviderConnectionError) as exc:
            claimed.provider_name = self._provider_name()
            if self.allow_live_demo:
                self.render_repository.update_status(
                    claimed,
                    "FAILED",
                    error_code="PROVIDER_SUBMIT_ERROR",
                    error_message="Visual generation provider request failed",
                )
                raise AppError(
                    "Visual generation provider request failed", 502
                ) from exc
            category = (
                "submit_unknown_timeout"
                if isinstance(exc, ProviderTimeoutError)
                else "submit_unknown_network"
            )
            self.render_repository.update_status(
                claimed,
                "SUBMIT_UNKNOWN",
                error_code=category,
                error_message=(
                    "Provider acknowledgement is unavailable; automatic "
                    "resubmission is blocked"
                ),
            )
            raise AppError(
                "Provider submission acknowledgement is unknown; "
                "automatic retry is blocked",
                502,
            ) from exc
        except ProviderError as exc:
            category, message, status_code = self._classify_provider_error(exc)
            claimed.provider_name = self._provider_name()
            self.render_repository.update_status(
                claimed,
                "FAILED",
                error_code=category,
                error_message=message,
            )
            raise AppError(message, status_code) from exc

        if not submission.provider_task_id.strip():
            self.render_repository.update_status(
                claimed,
                "FAILED",
                error_code="invalid_provider_output",
                error_message="Provider returned an invalid task identifier",
            )
            raise AppError("Provider returned an invalid task identifier", 502)
        task = self._record_submission(claimed, submission)
        return VideoRenderExecutionResult(
            task=task,
            artifact=None,
            external_call=True,
        )

    async def refresh(self, task_id: int) -> VideoRenderExecutionResult:
        self._require_execution_enabled()
        task = self.render_service.get_render_task(task_id)
        artifact = self.artifact_repository.get_by_task_id(task.id)
        if task.status == "SUCCEEDED" and artifact is not None:
            return VideoRenderExecutionResult(task, artifact, False)
        if task.status in NO_REFRESH_TERMINAL_STATUSES:
            return VideoRenderExecutionResult(task, artifact, False)
        if task.status not in REFRESHABLE_STATUSES:
            raise AppError(
                f"Video render task cannot refresh from {task.status}",
                409,
            )
        if task.provider_task_id is None:
            raise AppError("Video render task has not been submitted", 409)

        previous_status = task.status
        claimed = self.render_repository.claim_for_refresh(
            task.id, previous_status
        )
        if claimed is None:
            raise AppError("Video render task refresh is already in progress", 409)

        try:
            snapshot = await self.provider.fetch(task.provider_task_id)
        except ProviderError as exc:
            category, message, status_code = self._classify_provider_error(exc)
            self.render_repository.update_status(
                claimed,
                previous_status,
                error_code=f"refresh_{category}",
                error_message=message,
            )
            raise AppError(message, status_code) from exc

        if snapshot.provider_task_id != task.provider_task_id:
            self._restore_after_invalid_refresh(
                claimed,
                previous_status,
                "Provider returned a mismatched render task",
            )
        if snapshot.status == "UNKNOWN":
            self._restore_after_invalid_refresh(
                claimed,
                previous_status,
                "Provider returned an unknown render status",
            )
        if snapshot.status == "SUCCEEDED" and not snapshot.provider_output_url:
            self._restore_after_invalid_refresh(
                claimed,
                previous_status,
                "Provider returned no video result",
            )

        if snapshot.status == "SUCCEEDED":
            return await self._persist_succeeded_video(
                claimed,
                snapshot.provider_output_url or "",
            )
        if snapshot.status == "FAILED":
            task = self.render_repository.update_status(
                claimed,
                "FAILED",
                error_code="provider_failed",
                error_message="Provider reported video generation failed",
            )
        else:
            task = self.render_repository.update_status(
                claimed,
                snapshot.status,
                error_code=None,
                error_message=None,
            )
        artifact = self.artifact_repository.get_by_task_id(task.id)
        return VideoRenderExecutionResult(task, artifact, True)

    def _record_submission(
        self,
        task: VideoRenderTask,
        submission: VisualTaskSubmission,
    ) -> VideoRenderTask:
        status = submission.status
        error_code = None
        error_message = None
        if status in {"UNKNOWN", "SUCCEEDED"}:
            status = "SUBMITTED"
        elif status == "FAILED":
            error_code = "PROVIDER_SUBMISSION_FAILED"
            error_message = "Visual generation provider rejected the task"
        return self.render_repository.record_submission(
            task,
            provider_name=self._provider_name(),
            provider_task_id=submission.provider_task_id,
            status=status,
            error_code=error_code,
            error_message=error_message,
        )

    async def _persist_succeeded_video(
        self,
        task: VideoRenderTask,
        provider_output_url: str,
    ) -> VideoRenderExecutionResult:
        if self.output_fetcher is None or self.artifact_storage is None:
            task = self.render_repository.update_status(
                task,
                "ARTIFACT_PERSIST_FAILED",
                error_code="artifact_storage_not_configured",
                error_message="Artifact storage is not configured",
            )
            raise AppError("Artifact storage is not configured", 503)

        stored_path: str | None = None
        try:
            fetched = await self.output_fetcher.fetch(provider_output_url)
            stored = self.artifact_storage.store(
                task_id=task.id,
                content=fetched.content,
                content_type=fetched.content_type,
            )
            stored_path = stored.relative_path
            artifact = self.artifact_repository.finalize_succeeded(
                task,
                VideoRenderArtifactCreate(
                    provider_output_url=None,
                    storage_path=stored.relative_path,
                    metadata={
                        "source_kind": "provider_output",
                        "content_type": stored.content_type,
                        "size_bytes": stored.size_bytes,
                        "sha256": stored.sha256,
                    },
                ),
            )
        except VideoArtifactError as exc:
            task = self.render_repository.update_status(
                task,
                "ARTIFACT_PERSIST_FAILED",
                error_code=exc.category,
                error_message=exc.safe_message,
            )
            raise AppError(exc.safe_message, 502) from exc
        except Exception as exc:
            self.session.rollback()
            if stored_path is not None:
                self.artifact_storage.delete(stored_path)
            self.render_repository.update_status(
                task,
                "ARTIFACT_PERSIST_FAILED",
                error_code="artifact_persist_failed",
                error_message="Video artifact could not be persisted",
            )
            raise AppError("Video artifact could not be persisted", 500) from exc
        return VideoRenderExecutionResult(task, artifact, True)

    def _restore_after_invalid_refresh(
        self,
        task: VideoRenderTask,
        previous_status: str,
        message: str,
    ) -> None:
        self.render_repository.update_status(
            task,
            previous_status,
            error_code="refresh_invalid_provider_output",
            error_message=message,
        )
        raise AppError(message, 502)

    @staticmethod
    def _classify_provider_error(
        exc: ProviderError,
    ) -> tuple[str, str, int]:
        if isinstance(exc, ProviderAuthenticationError):
            return "authentication", "Wanx authentication failed", 502
        if isinstance(exc, ProviderQuotaError):
            return (
                "quota_or_rate_limit",
                "Wanx quota or rate limit blocked the request",
                429,
            )
        if isinstance(exc, ProviderTimeoutError):
            return "timeout", "Wanx request timed out", 504
        if isinstance(exc, ProviderConnectionError):
            return "network", "Wanx service is unavailable", 502
        if isinstance(exc, ProviderConfigurationError):
            return (
                "provider_not_configured",
                "Wanx provider is not configured",
                503,
            )
        if isinstance(exc, ProviderModelError):
            return (
                "invalid_provider_output",
                "Wanx returned an invalid response",
                502,
            )
        return "unknown", "Visual generation provider request failed", 502

    def _provider_name(self) -> str:
        name = type(self.provider).__name__
        return name.removesuffix("Provider").lower()

    def _require_execution_enabled(self) -> None:
        enabled = self.settings.enable_video_render_execution
        live_enabled = (
            self.allow_live_demo and self.settings.enable_live_wanx_demo
        )
        if not enabled and not live_enabled:
            raise AppError(
                "Video render execution is disabled by the server",
                status_code=503,
            )
