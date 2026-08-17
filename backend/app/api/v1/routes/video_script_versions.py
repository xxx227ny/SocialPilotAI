from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.video_script_version import (
    VideoScriptActivateRead,
    VideoScriptCreateRead,
    VideoScriptCreateRequest,
    VideoScriptDraftRequest,
    VideoScriptPreflightRead,
    VideoScriptVersionRead,
)
from app.services.video_script_preflight import VideoScriptPreflightService
from app.services.video_script_version_service import VideoScriptVersionService

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]


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
