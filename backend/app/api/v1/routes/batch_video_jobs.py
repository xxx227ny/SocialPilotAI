from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceProviderSettingsDep
from app.db.session import get_db
from app.schemas.batch_video import (
    BatchQwenScriptCreateRead,
    BatchQwenScriptCreateRequest,
    BatchQwenScriptPreflightRead,
    BatchQwenScriptRequest,
    BatchVideoCreateRead,
    BatchVideoCreateRequest,
    BatchVideoJobRead,
    BatchVideoPreflightRead,
    BatchVideoRequest,
    BatchVideoVariantRead,
)
from app.services.batch_qwen_script_service import BatchQwenScriptService
from app.services.batch_video_job_service import BatchVideoJobService
from app.services.batch_video_preflight import BatchVideoPreflightService

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
SettingsDep = WorkspaceProviderSettingsDep


@router.post("/batch-video-jobs/preflight", response_model=BatchVideoPreflightRead)
def preflight(data: BatchVideoRequest, db: Db) -> BatchVideoPreflightRead:
    return BatchVideoPreflightService(db).run(data)


@router.post(
    "/batch-video-jobs",
    response_model=BatchVideoCreateRead,
    status_code=status.HTTP_201_CREATED,
)
def create(data: BatchVideoCreateRequest, db: Db) -> BatchVideoCreateRead:
    return BatchVideoJobService(db).create(data)


@router.get("/batch-video-jobs/{batch_id}", response_model=BatchVideoJobRead)
def get_batch(batch_id: int, db: Db) -> BatchVideoJobRead:
    return BatchVideoJobService(db).get_batch(batch_id)


@router.get(
    "/batch-video-jobs/{batch_id}/variants",
    response_model=list[BatchVideoVariantRead],
)
def list_variants(batch_id: int, db: Db) -> list[BatchVideoVariantRead]:
    return BatchVideoJobService(db).list_variants(batch_id)


@router.get("/batch-video-variants/{variant_id}", response_model=BatchVideoVariantRead)
def get_variant(variant_id: int, db: Db) -> BatchVideoVariantRead:
    return BatchVideoJobService(db).get_variant(variant_id)


@router.post("/batch-video-jobs/{batch_id}/pause", response_model=BatchVideoJobRead)
def pause(batch_id: int, db: Db) -> BatchVideoJobRead:
    return BatchVideoJobService(db).pause(batch_id)


@router.post("/batch-video-jobs/{batch_id}/resume", response_model=BatchVideoJobRead)
def resume(batch_id: int, db: Db) -> BatchVideoJobRead:
    return BatchVideoJobService(db).resume(batch_id)


@router.post("/batch-video-jobs/{batch_id}/cancel", response_model=BatchVideoJobRead)
def cancel(batch_id: int, db: Db) -> BatchVideoJobRead:
    return BatchVideoJobService(db).cancel(batch_id)


@router.post(
    "/batch-video-jobs/{batch_id}/qwen-scripts/preflight",
    response_model=BatchQwenScriptPreflightRead,
)
def preflight_qwen_scripts(
    batch_id: int, data: BatchQwenScriptRequest, db: Db, settings: SettingsDep
) -> BatchQwenScriptPreflightRead:
    return BatchQwenScriptService(db, settings).preflight(batch_id, data)


@router.post(
    "/batch-video-jobs/{batch_id}/qwen-scripts",
    response_model=BatchQwenScriptCreateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_or_recover_qwen_scripts(
    batch_id: int,
    data: BatchQwenScriptCreateRequest,
    db: Db,
    settings: SettingsDep,
) -> BatchQwenScriptCreateRead:
    return BatchQwenScriptService(db, settings).create_or_recover(batch_id, data)
