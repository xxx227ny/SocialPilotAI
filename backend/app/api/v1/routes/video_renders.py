from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import (
    VideoRenderExecutionGateDep,
    VisualProviderDep,
    get_visual_generation_provider,
)
from app.core.config import Settings, get_settings, settings
from app.core.exceptions import AppError
from app.db.session import get_db
from app.providers.visual_base import VisualGenerationProvider
from app.schemas.video import VideoProjectSchema
from app.schemas.video_render import (
    LiveVideoRenderRequest,
    VideoRenderExecutionSchema,
    VideoRenderPreflightRead,
    VideoRenderTaskCreate,
    VideoRenderTaskSchema,
)
from app.schemas.video_render_artifact import VideoRenderArtifactSchema
from app.services.live_video_render_service import LiveVideoRenderService
from app.services.video_render_execution_service import (
    VideoRenderExecutionService,
)
from app.services.video_render_preflight import (
    VideoProjectQueryService,
    VideoRenderPreflightService,
)
from app.services.video_render_service import VideoRenderService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
VisualProviderFactory = Callable[[], VisualGenerationProvider]


def get_live_visual_provider_factory() -> VisualProviderFactory:
    return get_visual_generation_provider


LiveVisualProviderFactoryDep = Annotated[
    VisualProviderFactory, Depends(get_live_visual_provider_factory)
]


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
    "/video-projects/{video_project_id}/render-artifacts",
    response_model=list[VideoRenderArtifactSchema],
)
def list_video_render_artifacts(
    video_project_id: int, db: DbSession
) -> list[VideoRenderArtifactSchema]:
    return VideoRenderService(
        db
    ).list_succeeded_artifacts_by_video_project(video_project_id)


@router.get(
    "/video-projects/{video_project_id}",
    response_model=VideoProjectSchema,
)
def get_video_project(
    video_project_id: int,
    db: DbSession,
) -> VideoProjectSchema:
    return VideoProjectQueryService(db).get(video_project_id)


@router.get(
    "/video-projects/{video_project_id}/render-preflight",
    response_model=VideoRenderPreflightRead,
)
def get_video_render_preflight(
    video_project_id: int,
    db: DbSession,
    app_settings: SettingsDep,
) -> VideoRenderPreflightRead:
    return VideoRenderPreflightService(db, app_settings).run(video_project_id)


@router.post(
    "/video-projects/{video_project_id}/live-render",
    response_model=VideoRenderExecutionSchema,
)
async def create_live_video_render(
    video_project_id: int,
    data: LiveVideoRenderRequest,
    db: DbSession,
    provider_factory: LiveVisualProviderFactoryDep,
) -> VideoRenderExecutionSchema:
    if not settings.enable_live_wanx_demo:
        raise AppError("Live Wanx demo is disabled", status_code=403)
    if data.confirm_live_generation is not True:
        raise AppError("Live generation confirmation is required", 422)
    result = await LiveVideoRenderService(
        db, provider_factory
    ).execute(video_project_id)
    return VideoRenderExecutionSchema.model_validate(result)


@router.get(
    "/video-render-tasks/{task_id}", response_model=VideoRenderTaskSchema
)
def get_video_render_task(
    task_id: int, db: DbSession
) -> VideoRenderTaskSchema:
    return VideoRenderService(db).get_render_task(task_id)


@router.post(
    "/video-render-tasks/{task_id}/submit",
    response_model=VideoRenderExecutionSchema,
)
async def submit_video_render_task(
    task_id: int,
    db: DbSession,
    execution_gate: VideoRenderExecutionGateDep,
    provider: VisualProviderDep,
    app_settings: SettingsDep,
) -> VideoRenderExecutionSchema:
    del execution_gate
    result = await VideoRenderExecutionService(
        db, provider, app_settings
    ).submit(task_id)
    return VideoRenderExecutionSchema.model_validate(result)


@router.post(
    "/video-render-tasks/{task_id}/refresh",
    response_model=VideoRenderExecutionSchema,
)
async def refresh_video_render_task(
    task_id: int,
    db: DbSession,
    execution_gate: VideoRenderExecutionGateDep,
    provider: VisualProviderDep,
    app_settings: SettingsDep,
) -> VideoRenderExecutionSchema:
    del execution_gate
    result = await VideoRenderExecutionService(
        db, provider, app_settings
    ).refresh(task_id)
    return VideoRenderExecutionSchema.model_validate(result)
