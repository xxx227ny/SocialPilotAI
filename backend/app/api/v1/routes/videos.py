from typing import Annotated

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import (
    VideoProjectTextProviderDep,
    WorkspaceProviderSettingsDep,
)
from app.db.session import get_db
from app.schemas.execution import ExecutionJobCreateRead
from app.schemas.video import (
    InitialVideoProjectExecutionRequest,
    InitialVideoProjectPreflightRead,
    InitialVideoProjectSourceRead,
    InitialVideoProjectSourceRequest,
    VideoProjectRequest,
    VideoProjectSchema,
)
from app.services.content_studio_service import ContentStudioService
from app.services.initial_video_project_job_service import (
    InitialVideoProjectJobService,
)
from app.services.initial_video_project_preflight import (
    InitialVideoProjectPreflightService,
    InitialVideoProjectSourceQueryService,
)
from app.services.video_render_preflight import VideoProjectQueryService

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = WorkspaceProviderSettingsDep


@router.post(
    "/{product_id}/video-projects", response_model=VideoProjectSchema
)
def generate_video_project(
    product_id: int,
    db: DbSession,
    provider: VideoProjectTextProviderDep,
    request: Annotated[VideoProjectRequest, Body()],
) -> VideoProjectSchema:
    return ContentStudioService(db, provider).generate_for_product(
        product_id, request
    )


@router.get(
    "/{product_id}/video-projects/source",
    response_model=InitialVideoProjectSourceRead,
)
def get_initial_video_project_source(
    product_id: int,
    db: DbSession,
) -> InitialVideoProjectSourceRead:
    return InitialVideoProjectSourceQueryService(db).get_for_product(product_id)


@router.post(
    "/{product_id}/video-projects/preflight",
    response_model=InitialVideoProjectPreflightRead,
)
def preflight_initial_video_project(
    product_id: int,
    request: InitialVideoProjectSourceRequest,
    db: DbSession,
    app_settings: SettingsDep,
) -> InitialVideoProjectPreflightRead:
    return InitialVideoProjectPreflightService(db, app_settings).run(
        product_id, request
    )


@router.post(
    "/{product_id}/video-projects/execute",
    response_model=ExecutionJobCreateRead,
    status_code=201,
)
def execute_initial_video_project(
    product_id: int,
    request: InitialVideoProjectExecutionRequest,
    db: DbSession,
    app_settings: SettingsDep,
) -> ExecutionJobCreateRead:
    return InitialVideoProjectJobService(db, app_settings).enqueue(
        product_id, request
    )


@router.get(
    "/{product_id}/video-projects/latest",
    response_model=VideoProjectSchema,
)
def get_latest_video_project(
    product_id: int,
    db: DbSession,
) -> VideoProjectSchema:
    return VideoProjectQueryService(db).get_latest_for_product(product_id)
