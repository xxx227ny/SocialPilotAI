from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import (
    ProviderOutputFetcherDep,
    VideoArtifactStorageDep,
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
    VideoRenderArtifactSafeRead,
    VideoRenderExecutionSchema,
    VideoRenderOperationRead,
    VideoRenderPreflightRead,
    VideoRenderTaskCreate,
    VideoRenderTaskSchema,
)
from app.schemas.video_render_artifact import VideoRenderArtifactSchema
from app.services.live_video_render_service import LiveVideoRenderService
from app.services.video_artifact_http import (
    RangeNotSatisfiable,
    parse_byte_range,
    safe_artifact_filename,
    stream_file,
)
from app.services.video_artifact_storage import (
    LocalVideoArtifactStorage,
    VideoArtifactError,
    VideoArtifactStorage,
)
from app.services.video_render_execution_service import (
    VideoRenderExecutionService,
)
from app.services.video_render_operation_service import (
    VideoArtifactAccessService,
    VideoProjectRenderExecutionService,
    VideoRenderRecoveryService,
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


def get_optional_recovery_artifact_storage(
    app_settings: SettingsDep,
) -> VideoArtifactStorage | None:
    configured = (app_settings.video_artifact_storage_root or "").strip()
    if not configured:
        return None
    try:
        return LocalVideoArtifactStorage(
            Path(configured),
            app_settings.video_artifact_max_bytes,
        )
    except VideoArtifactError:
        return None


RecoveryArtifactStorageDep = Annotated[
    VideoArtifactStorage | None,
    Depends(get_optional_recovery_artifact_storage),
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
    "/video-projects/{video_project_id}/render-execution",
    response_model=VideoRenderOperationRead,
)
async def execute_video_project_render(
    video_project_id: int,
    db: DbSession,
    execution_gate: VideoRenderExecutionGateDep,
    provider: VisualProviderDep,
    app_settings: SettingsDep,
    output_fetcher: ProviderOutputFetcherDep,
    artifact_storage: VideoArtifactStorageDep,
) -> VideoRenderOperationRead:
    del execution_gate
    return await VideoProjectRenderExecutionService(
        db,
        provider,
        app_settings,
        output_fetcher,
        artifact_storage,
    ).execute(video_project_id)


@router.get(
    "/video-projects/{video_project_id}/render-tasks/latest",
    response_model=VideoRenderOperationRead,
)
def get_latest_video_render_task(
    video_project_id: int,
    db: DbSession,
    artifact_storage: RecoveryArtifactStorageDep,
) -> VideoRenderOperationRead:
    return VideoRenderRecoveryService(
        db, artifact_storage
    ).get_latest(video_project_id)


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


@router.get(
    "/video-render-tasks/{task_id}/recovery",
    response_model=VideoRenderOperationRead,
)
def recover_video_render_task(
    task_id: int,
    db: DbSession,
    artifact_storage: RecoveryArtifactStorageDep,
) -> VideoRenderOperationRead:
    return VideoRenderRecoveryService(
        db, artifact_storage
    ).get_task(task_id)


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
    output_fetcher: ProviderOutputFetcherDep,
    artifact_storage: VideoArtifactStorageDep,
) -> VideoRenderExecutionSchema:
    del execution_gate
    result = await VideoRenderExecutionService(
        db,
        provider,
        app_settings,
        output_fetcher=output_fetcher,
        artifact_storage=artifact_storage,
    ).refresh(task_id)
    return VideoRenderExecutionSchema.model_validate(result)


@router.get(
    "/video-render-artifacts/{artifact_id}",
    response_model=VideoRenderArtifactSafeRead,
)
def get_video_render_artifact(
    artifact_id: int,
    db: DbSession,
    artifact_storage: VideoArtifactStorageDep,
) -> VideoRenderArtifactSafeRead:
    return VideoArtifactAccessService(
        db, artifact_storage
    ).get_metadata(artifact_id)


def _artifact_headers(
    *,
    filename: str,
    content_type: str,
    content_length: int,
    disposition: str,
) -> dict[str, str]:
    return {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Content-Length": str(content_length),
        "Content-Type": content_type,
        "X-Content-Type-Options": "nosniff",
    }


@router.get("/video-render-artifacts/{artifact_id}/content")
def get_video_render_artifact_content(
    artifact_id: int,
    request: Request,
    db: DbSession,
    artifact_storage: VideoArtifactStorageDep,
) -> StreamingResponse:
    verified = VideoArtifactAccessService(
        db, artifact_storage
    ).resolve_verified(artifact_id)
    filename = safe_artifact_filename(
        artifact_id,
        verified.artifact.video_render_task_id,
        verified.path.suffix,
    )
    range_header = request.headers.get("range")
    if range_header is None:
        headers = _artifact_headers(
            filename=filename,
            content_type=verified.content_type,
            content_length=verified.size_bytes,
            disposition="inline",
        )
        return StreamingResponse(
            stream_file(verified.path),
            status_code=200,
            headers=headers,
            media_type=verified.content_type,
        )
    try:
        requested = parse_byte_range(range_header, verified.size_bytes)
    except RangeNotSatisfiable:
        return Response(
            status_code=416,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{verified.size_bytes}",
                "Content-Length": "0",
            },
        )
    headers = _artifact_headers(
        filename=filename,
        content_type=verified.content_type,
        content_length=requested.length,
        disposition="inline",
    )
    headers["Content-Range"] = (
        f"bytes {requested.start}-{requested.end}/{verified.size_bytes}"
    )
    return StreamingResponse(
        stream_file(
            verified.path,
            start=requested.start,
            length=requested.length,
        ),
        status_code=206,
        headers=headers,
        media_type=verified.content_type,
    )


@router.head("/video-render-artifacts/{artifact_id}/content")
def head_video_render_artifact_content(
    artifact_id: int,
    db: DbSession,
    artifact_storage: VideoArtifactStorageDep,
) -> Response:
    verified = VideoArtifactAccessService(
        db, artifact_storage
    ).resolve_verified(artifact_id)
    filename = safe_artifact_filename(
        artifact_id,
        verified.artifact.video_render_task_id,
        verified.path.suffix,
    )
    return Response(
        status_code=200,
        headers=_artifact_headers(
            filename=filename,
            content_type=verified.content_type,
            content_length=verified.size_bytes,
            disposition="inline",
        ),
    )


@router.get("/video-render-artifacts/{artifact_id}/download")
def download_video_render_artifact(
    artifact_id: int,
    db: DbSession,
    artifact_storage: VideoArtifactStorageDep,
) -> StreamingResponse:
    verified = VideoArtifactAccessService(
        db, artifact_storage
    ).resolve_verified(artifact_id)
    filename = safe_artifact_filename(
        artifact_id,
        verified.artifact.video_render_task_id,
        verified.path.suffix,
    )
    return StreamingResponse(
        stream_file(verified.path),
        status_code=200,
        headers=_artifact_headers(
            filename=filename,
            content_type=verified.content_type,
            content_length=verified.size_bytes,
            disposition="attachment",
        ),
        media_type=verified.content_type,
    )
