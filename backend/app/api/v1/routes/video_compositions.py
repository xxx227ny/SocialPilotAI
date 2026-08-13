from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import VideoArtifactStorageDep, VideoCompositionGateDep
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.video_composition import (
    VideoCompositionArtifactRead,
    VideoCompositionPreflightRead,
    VideoCompositionPreflightRequest,
    VideoCompositionRead,
    VideoCompositionSubmitRead,
    VideoCompositionSubmitRequest,
)
from app.services.video_artifact_http import (
    RangeNotSatisfiable,
    parse_byte_range,
    stream_file,
)
from app.services.video_composition_job_service import VideoCompositionJobService
from app.services.video_composition_preflight import VideoCompositionPreflightService
from app.services.video_composition_service import (
    VideoCompositionArtifactAccessService,
    VideoCompositionService,
)

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/products/{product_id}/video-compositions/preflight",
    response_model=VideoCompositionPreflightRead,
)
def preflight_composition(
    product_id: int,
    data: VideoCompositionPreflightRequest,
    db: Db,
    storage: VideoArtifactStorageDep,
    gate: VideoCompositionGateDep,
) -> VideoCompositionPreflightRead:
    del gate
    return VideoCompositionPreflightService(db, storage).run(product_id, data)


@router.post(
    "/products/{product_id}/video-compositions",
    response_model=VideoCompositionSubmitRead,
    status_code=status.HTTP_201_CREATED,
)
def submit_composition(
    product_id: int,
    data: VideoCompositionSubmitRequest,
    db: Db,
    settings: SettingsDep,
    gate: VideoCompositionGateDep,
) -> VideoCompositionSubmitRead:
    del gate
    return VideoCompositionJobService(db, settings).enqueue(product_id, data)


@router.get("/video-compositions/{composition_id}", response_model=VideoCompositionRead)
def get_composition(
    composition_id: int, db: Db, settings: SettingsDep
) -> VideoCompositionRead:
    return VideoCompositionService(db, settings).get(composition_id)


@router.get(
    "/video-composition-artifacts/{artifact_id}",
    response_model=VideoCompositionArtifactRead,
)
def get_composition_artifact(
    artifact_id: int, db: Db, settings: SettingsDep
) -> VideoCompositionArtifactRead:
    artifact, _ = VideoCompositionArtifactAccessService(db, settings).resolve(
        artifact_id
    )
    return VideoCompositionArtifactRead.model_validate(artifact)


def _headers(length: int, filename: str) -> dict[str, str]:
    return {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": "video/mp4",
        "Content-Disposition": f'inline; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }


@router.get("/video-composition-artifacts/{artifact_id}/content")
def content(artifact_id: int, request: Request, db: Db, settings: SettingsDep):
    artifact, path = VideoCompositionArtifactAccessService(db, settings).resolve(
        artifact_id
    )
    name = f"composition-{artifact.composition_id}-{artifact.id}.mp4"
    range_value = request.headers.get("range")
    if range_value is None:
        return StreamingResponse(
            stream_file(path),
            media_type="video/mp4",
            headers=_headers(artifact.size_bytes, name),
        )
    try:
        byte_range = parse_byte_range(range_value, artifact.size_bytes)
    except RangeNotSatisfiable:
        return Response(
            status_code=416,
            headers={
                "Content-Range": f"bytes */{artifact.size_bytes}",
                "Content-Length": "0",
            },
        )
    headers = _headers(byte_range.length, name)
    headers["Content-Range"] = (
        f"bytes {byte_range.start}-{byte_range.end}/{artifact.size_bytes}"
    )
    return StreamingResponse(
        stream_file(path, start=byte_range.start, length=byte_range.length),
        status_code=206,
        media_type="video/mp4",
        headers=headers,
    )


@router.head("/video-composition-artifacts/{artifact_id}/content")
def head_content(artifact_id: int, db: Db, settings: SettingsDep) -> Response:
    artifact, _ = VideoCompositionArtifactAccessService(db, settings).resolve(
        artifact_id
    )
    return Response(
        status_code=200,
        headers=_headers(
            artifact.size_bytes,
            f"composition-{artifact.composition_id}-{artifact.id}.mp4",
        ),
    )
