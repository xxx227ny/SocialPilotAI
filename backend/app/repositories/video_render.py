from sqlalchemy import select, update
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

    def get_by_provider_task_id(
        self, provider_task_id: str
    ) -> VideoRenderTask | None:
        return self.session.scalar(
            select(VideoRenderTask).where(
                VideoRenderTask.provider_task_id == provider_task_id
            )
        )

    def get_latest_by_video_project(
        self, video_project_id: int
    ) -> VideoRenderTask | None:
        statement = (
            select(VideoRenderTask)
            .where(VideoRenderTask.video_project_id == video_project_id)
            .order_by(
                VideoRenderTask.created_at.desc(),
                VideoRenderTask.id.desc(),
            )
            .limit(1)
        )
        return self.session.scalar(statement)

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

    def claim_for_submission(self, task_id: int) -> VideoRenderTask | None:
        result = self.session.execute(
            update(VideoRenderTask)
            .where(
                VideoRenderTask.id == task_id,
                VideoRenderTask.status == "CREATED",
                VideoRenderTask.provider_task_id.is_(None),
            )
            .values(
                status="SUBMITTING",
                error_code=None,
                error_message=None,
            )
            .execution_options(synchronize_session="fetch")
        )
        if result.rowcount != 1:
            self.session.rollback()
            return None
        self.session.commit()
        return self.get(task_id)

    def claim_for_refresh(
        self,
        task_id: int,
        expected_status: str,
    ) -> VideoRenderTask | None:
        result = self.session.execute(
            update(VideoRenderTask)
            .where(
                VideoRenderTask.id == task_id,
                VideoRenderTask.status == expected_status,
                VideoRenderTask.provider_task_id.is_not(None),
            )
            .values(
                status="REFRESHING",
                error_code=None,
                error_message=None,
            )
            .execution_options(synchronize_session="fetch")
        )
        if result.rowcount != 1:
            self.session.rollback()
            return None
        self.session.commit()
        return self.get(task_id)

    def record_submission(
        self,
        task: VideoRenderTask,
        *,
        provider_name: str,
        provider_task_id: str,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> VideoRenderTask:
        task.provider_name = provider_name
        task.provider_task_id = provider_task_id
        task.status = status
        task.error_code = error_code
        task.error_message = error_message
        self.session.commit()
        self.session.refresh(task)
        return task

    def update_status(
        self,
        task: VideoRenderTask,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> VideoRenderTask:
        task.status = status
        task.error_code = error_code
        task.error_message = error_message
        self.session.commit()
        self.session.refresh(task)
        return task
