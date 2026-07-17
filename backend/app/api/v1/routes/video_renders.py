from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.video_render import VideoRenderTaskCreate, VideoRenderTaskSchema
from app.services.video_render_service import VideoRenderService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/video-projects/{video_project_id}/render-tasks",
    response_model=VideoRenderTaskSchema,
    status_code=status.HTTP_201_CREATED,
)
def create_video_render_task(
    video_project_id: int,
    data: VideoRenderTaskCreate,
    db: DbSession,
) -> VideoRenderTaskSchema:
    return VideoRenderService(db).create_render_task(video_project_id, data)


@router.get(
    "/video-render-tasks/{task_id}", response_model=VideoRenderTaskSchema
)
def get_video_render_task(
    task_id: int, db: DbSession
) -> VideoRenderTaskSchema:
    return VideoRenderService(db).get_render_task(task_id)
