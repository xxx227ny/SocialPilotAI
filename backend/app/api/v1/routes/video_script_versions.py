from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.execution import ExecutionJobCreateRead
from app.schemas.video_script_version import (
    QwenScriptJobCreateRequest,
    QwenScriptPreflightRead,
    QwenScriptPreflightRequest,
    VideoScriptActivateRead,
    VideoScriptCreateRead,
    VideoScriptCreateRequest,
    VideoScriptDraftRequest,
    VideoScriptPreflightRead,
    VideoScriptVersionRead,
)
from app.services.qwen_video_script_job_service import QwenVideoScriptJobService
from app.services.qwen_video_script_preflight import QwenVideoScriptPreflightService
from app.services.video_script_preflight import VideoScriptPreflightService
from app.services.video_script_version_service import VideoScriptVersionService

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/batch-video-variants/{variant_id}/script-versions/preflight",
    response_model=VideoScriptPreflightRead,
)
def preflight(
    variant_id: int, data: VideoScriptDraftRequest, db: Db
) -> VideoScriptPreflightRead:
    return VideoScriptPreflightService(db).run(variant_id, data)


@router.post(
    "/batch-video-variants/{variant_id}/script-versions",
    response_model=VideoScriptCreateRead,
    status_code=status.HTTP_201_CREATED,
)
def create(
    variant_id: int, data: VideoScriptCreateRequest, db: Db
) -> VideoScriptCreateRead:
    return VideoScriptVersionService(db).create(variant_id, data)


@router.get(
    "/batch-video-variants/{variant_id}/script-versions",
    response_model=list[VideoScriptVersionRead],
)
def list_versions(variant_id: int, db: Db) -> list[VideoScriptVersionRead]:
    return VideoScriptVersionService(db).list(variant_id)


@router.get(
    "/batch-video-variants/{variant_id}/script-versions/{version_id}",
    response_model=VideoScriptVersionRead,
)
def get_version(variant_id: int, version_id: int, db: Db) -> VideoScriptVersionRead:
    return VideoScriptVersionService(db).get(variant_id, version_id)


@router.post(
    "/batch-video-variants/{variant_id}/script-versions/{version_id}/activate",
    response_model=VideoScriptActivateRead,
)
def activate(variant_id: int, version_id: int, db: Db) -> VideoScriptActivateRead:
    return VideoScriptVersionService(db).activate(variant_id, version_id)


@router.post(
    "/batch-video-variants/{variant_id}/qwen-script/preflight",
    response_model=QwenScriptPreflightRead,
)
def qwen_preflight(
    variant_id: int,
    data: QwenScriptPreflightRequest,
    db: Db,
    settings: SettingsDep,
) -> QwenScriptPreflightRead:
    return QwenVideoScriptPreflightService(db, settings).run(variant_id, data)


@router.post(
    "/batch-video-variants/{variant_id}/qwen-script/jobs",
    response_model=ExecutionJobCreateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_qwen_job(
    variant_id: int,
    data: QwenScriptJobCreateRequest,
    db: Db,
    settings: SettingsDep,
) -> ExecutionJobCreateRead:
    return QwenVideoScriptJobService(db, settings).enqueue(variant_id, data)
