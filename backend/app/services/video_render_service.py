from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import VideoRenderTask
from app.repositories.video import VideoProjectRepository
from app.repositories.video_render import VideoRenderTaskRepository
from app.schemas.video import VideoSceneSchema
from app.schemas.video_render import VideoRenderTaskCreate


class VideoRenderService:
    """Create and read local render tasks without any provider interaction."""

    def __init__(self, session: Session) -> None:
        self.video_repository = VideoProjectRepository(session)
        self.render_repository = VideoRenderTaskRepository(session)

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
