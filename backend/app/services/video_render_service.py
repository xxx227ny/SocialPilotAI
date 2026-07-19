from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import VideoRenderArtifact, VideoRenderTask
from app.repositories.video import VideoProjectRepository
from app.repositories.video_render import VideoRenderTaskRepository
from app.repositories.video_render_artifact_repository import (
    VideoRenderArtifactRepository,
)
from app.schemas.video import VideoSceneSchema
from app.schemas.video_render import VideoRenderTaskCreate
from app.schemas.video_render_artifact import VideoRenderArtifactCreate

RENDER_TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"SUBMITTED", "CANCELED"}),
    "SUBMITTED": frozenset(
        {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED"}
    ),
    "PENDING": frozenset({"RUNNING", "SUCCEEDED", "FAILED", "CANCELED"}),
    "RUNNING": frozenset({"SUCCEEDED", "FAILED", "CANCELED"}),
    "SUCCEEDED": frozenset(),
    "FAILED": frozenset(),
    "CANCELED": frozenset(),
}


class VideoRenderService:
    """Create and read local render tasks without any provider interaction."""

    def __init__(self, session: Session) -> None:
        self.video_repository = VideoProjectRepository(session)
        self.render_repository = VideoRenderTaskRepository(session)
        self.artifact_repository = VideoRenderArtifactRepository(session)

    def create_render_task(
        self, video_project_id: int, data: VideoRenderTaskCreate
    ) -> VideoRenderTask:
        project = self.video_repository.get(video_project_id)
        if project is None:
            raise AppError("Video project not found", status_code=404)

        scene_data = next(
            (
                scene
                for scene in project.scenes
                if scene.get("sequence") == data.scene_sequence
            ),
            None,
        )
        if scene_data is None:
            raise AppError("Video scene not found", status_code=422)
        try:
            scene = VideoSceneSchema.model_validate(scene_data)
        except ValidationError as exc:
            raise AppError("Video scene is invalid", status_code=422) from exc
        if scene.duration_seconds <= 0:
            raise AppError("Video scene duration must be positive", status_code=422)

        existing = self.render_repository.get_by_idempotency_key(
            data.idempotency_key
        )
        if existing is not None:
            if (
                existing.video_project_id != video_project_id
                or existing.scene_sequence != data.scene_sequence
                or existing.resolution != data.resolution
            ):
                raise AppError(
                    "Idempotency key is already used for another render request",
                    status_code=409,
                )
            return existing

        return self.render_repository.create(
            video_project_id=project.id,
            scene_sequence=scene.sequence,
            render_prompt=self._build_render_prompt(
                scene=scene,
                aspect_ratio=project.aspect_ratio,
            ),
            duration_seconds=scene.duration_seconds,
            aspect_ratio=project.aspect_ratio,
            resolution=data.resolution,
            idempotency_key=data.idempotency_key,
        )

    def get_render_task(self, task_id: int) -> VideoRenderTask:
        task = self.render_repository.get(task_id)
        if task is None:
            raise AppError("Video render task not found", status_code=404)
        return task

    def transition_status(
        self,
        task_id: int,
        new_status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> VideoRenderTask:
        task = self.get_render_task(task_id)
        normalized_status = new_status.strip().upper()
        allowed = RENDER_TASK_TRANSITIONS.get(task.status)
        if allowed is None or normalized_status not in allowed:
            raise AppError(
                f"Render task cannot transition from {task.status} "
                f"to {normalized_status}",
                status_code=409,
            )
        if normalized_status == "FAILED" and not error_code:
            raise AppError(
                "Failed render tasks require an error code", status_code=422
            )
        return self.render_repository.update_status(
            task,
            normalized_status,
            error_code=error_code if normalized_status == "FAILED" else None,
            error_message=(
                error_message if normalized_status == "FAILED" else None
            ),
        )

    def save_artifact(
        self, task_id: int, data: VideoRenderArtifactCreate
    ) -> VideoRenderArtifact:
        task = self.get_render_task(task_id)
        if task.status != "SUCCEEDED":
            raise AppError(
                "Render artifact can only be saved for a succeeded task",
                status_code=409,
            )
        existing = self.artifact_repository.get_by_task_id(task_id)
        if existing is not None:
            return self.artifact_repository.update(existing, data)
        return self.artifact_repository.create(task_id, data)

    def get_artifact(self, task_id: int) -> VideoRenderArtifact:
        self.get_render_task(task_id)
        artifact = self.artifact_repository.get_by_task_id(task_id)
        if artifact is None:
            raise AppError("Video render artifact not found", status_code=404)
        return artifact

    def list_artifacts(self) -> list[VideoRenderArtifact]:
        return self.artifact_repository.list()

    def list_succeeded_artifacts_by_video_project(
        self, video_project_id: int
    ) -> list[VideoRenderArtifact]:
        if self.video_repository.get(video_project_id) is None:
            raise AppError("Video project not found", status_code=404)
        return self.artifact_repository.list_succeeded_by_video_project_id(
            video_project_id
        )

    @staticmethod
    def _build_render_prompt(
        scene: VideoSceneSchema, aspect_ratio: str
    ) -> str:
        return (
            f"Create a {scene.duration_seconds}-second {aspect_ratio} social "
            f"video scene. Shot type: {scene.shot_type}. Visual composition: "
            f"{scene.visual_description}. Action: {scene.action}. Keep the "
            "product visually consistent. Do not add subtitles, on-screen text, "
            "logos, or audio."
        )
