from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import VideoRenderTask


class VideoRenderTaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, task_id: int) -> VideoRenderTask | None:
        return self.session.get(VideoRenderTask, task_id)

    def get_by_idempotency_key(self, key: str) -> VideoRenderTask | None:
        return self.session.scalar(
            select(VideoRenderTask).where(VideoRenderTask.idempotency_key == key)
        )

    def create(
        self,
        *,
        video_project_id: int,
        scene_sequence: int,
        render_prompt: str,
        duration_seconds: int,
        aspect_ratio: str,
        resolution: str,
        idempotency_key: str,
    ) -> VideoRenderTask:
        task = VideoRenderTask(
            video_project_id=video_project_id,
            scene_sequence=scene_sequence,
            status="CREATED",
            provider_name=None,
            provider_task_id=None,
            render_prompt=render_prompt,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            idempotency_key=idempotency_key,
            error_code=None,
            error_message=None,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task
