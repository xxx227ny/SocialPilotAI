from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import VideoRenderArtifact, VideoRenderTask
from app.providers.base import ProviderError
from app.providers.visual_base import (
    VisualGenerationProvider,
    VisualGenerationRequest,
    VisualTaskSnapshot,
    VisualTaskSubmission,
)
from app.repositories.video_render import VideoRenderTaskRepository
from app.repositories.video_render_artifact_repository import (
    VideoRenderArtifactRepository,
)
from app.schemas.video_render_artifact import VideoRenderArtifactCreate
from app.services.video_render_service import VideoRenderService


@dataclass(frozen=True, slots=True)
class VideoRenderExecutionResult:
    task: VideoRenderTask
    artifact: VideoRenderArtifact | None
    external_call: bool


class VideoRenderExecutionService:
    """Orchestrate provider calls and synchronize local render state."""

    def __init__(
        self, session: Session, provider: VisualGenerationProvider
    ) -> None:
        self.provider = provider
        self.render_service = VideoRenderService(session)
        self.render_repository = VideoRenderTaskRepository(session)
        self.artifact_repository = VideoRenderArtifactRepository(session)

    async def submit(self, task_id: int) -> VideoRenderExecutionResult:
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
        except ProviderError as exc:
            self.render_repository.update_status(
                claimed,
                "FAILED",
                error_code="PROVIDER_SUBMIT_ERROR",
                error_message="Visual generation provider request failed",
            )
            raise AppError(
                "Visual generation provider request failed", 502
            ) from exc

        task = self._record_submission(claimed, submission)
        return VideoRenderExecutionResult(
            task=task,
            artifact=None,
            external_call=True,
        )

    async def refresh(self, task_id: int) -> VideoRenderExecutionResult:
        task = self.render_service.get_render_task(task_id)
        if task.provider_task_id is None:
            raise AppError("Video render task has not been submitted", 409)

        artifact = self.artifact_repository.get_by_task_id(task.id)
        if task.status == "SUCCEEDED" and artifact is not None:
            return VideoRenderExecutionResult(task, artifact, False)
        if task.status in {"FAILED", "CANCELED"}:
            return VideoRenderExecutionResult(task, artifact, False)

        try:
            snapshot = await self.provider.fetch(task.provider_task_id)
        except ProviderError as exc:
            raise AppError(
                "Visual generation provider request failed", 502
            ) from exc

        if snapshot.provider_task_id != task.provider_task_id:
            raise AppError("Provider returned a mismatched render task", 502)
        if snapshot.status == "UNKNOWN":
            raise AppError("Provider returned an unknown render status", 502)
        if snapshot.status == "SUCCEEDED" and not snapshot.provider_output_url:
            raise AppError("Provider returned no video result", 502)

        task = self._synchronize_snapshot(task, snapshot)
        artifact = self.artifact_repository.get_by_task_id(task.id)
        if snapshot.status == "SUCCEEDED":
            metadata = dict(snapshot.metadata)
            if snapshot.provider_request_id is not None:
                metadata["provider_request_id"] = snapshot.provider_request_id
            artifact = self.render_service.save_artifact(
                task.id,
                VideoRenderArtifactCreate(
                    provider_output_url=snapshot.provider_output_url,
                    metadata=metadata,
                ),
            )
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

    def _synchronize_snapshot(
        self,
        task: VideoRenderTask,
        snapshot: VisualTaskSnapshot,
    ) -> VideoRenderTask:
        if task.status == snapshot.status:
            return task
        return self.render_service.transition_status(
            task.id,
            snapshot.status,
            error_code=(
                snapshot.error_code or "PROVIDER_TASK_FAILED"
                if snapshot.status == "FAILED"
                else None
            ),
            error_message=(
                snapshot.error_message if snapshot.status == "FAILED" else None
            ),
        )

    def _provider_name(self) -> str:
        name = type(self.provider).__name__
        return name.removesuffix("Provider").lower()
