from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import (
    VideoArtifactStorageDep,
    VideoCompositionEnhancementGateDep,
    VideoCompositionGateDep,
)
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.db.session import get_db
from app.repositories.video_composition_enhancement import (
    VideoCompositionEnhancementRepository,
)
from app.schemas.video_composition import (
    VideoCompositionArtifactRead,
    VideoCompositionPreflightRead,
    VideoCompositionPreflightRequest,
    VideoCompositionRead,
    VideoCompositionSubmitRead,
    VideoCompositionSubmitRequest,
)
from app.schemas.video_composition_enhancement import (
    VideoCompositionAudioArtifactRead,
    VideoCompositionEnhancementArtifactRead,
    VideoCompositionEnhancementPreflightRead,
    VideoCompositionEnhancementPreflightRequest,
    VideoCompositionEnhancementRead,
    VideoCompositionEnhancementSubmitRead,
    VideoCompositionEnhancementSubmitRequest,
    VideoCompositionSubtitleArtifactRead,
)
from app.services.video_artifact_http import (
    RangeNotSatisfiable,
    parse_byte_range,
    stream_file,
)
from app.services.video_composition_enhancement_job_service import (
    VideoCompositionEnhancementJobService,
)
from app.services.video_composition_enhancement_preflight import (
    VideoCompositionEnhancementPreflightService,
)
from app.services.video_composition_enhancement_service import (
    VideoCompositionEnhancementArtifactAccessService,
    VideoCompositionEnhancementService,
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


@router.get(
    "/products/{product_id}/video-compositions/{composition_id}/audio-artifacts",
    response_model=list[VideoCompositionAudioArtifactRead],
)
def list_composition_audio_artifacts(
    product_id: int, composition_id: int, db: Db
) -> list[VideoCompositionAudioArtifactRead]:
    artifacts = VideoCompositionEnhancementRepository(db).list_audio(
        product_id, composition_id
    )
    return [
        VideoCompositionAudioArtifactRead.model_validate(item) for item in artifacts
    ]


@router.post(
    "/products/{product_id}/video-composition-enhancements/preflight",
    response_model=VideoCompositionEnhancementPreflightRead,
)
def preflight_composition_enhancement(
    product_id: int,
    data: VideoCompositionEnhancementPreflightRequest,
    db: Db,
    settings: SettingsDep,
    gate: VideoCompositionEnhancementGateDep,
) -> VideoCompositionEnhancementPreflightRead:
    del gate
    return VideoCompositionEnhancementPreflightService(db, settings).run(
        product_id, data
    )


@router.post(
    "/products/{product_id}/video-composition-enhancements",
    response_model=VideoCompositionEnhancementSubmitRead,
    status_code=status.HTTP_201_CREATED,
)
def submit_composition_enhancement(
    product_id: int,
    data: VideoCompositionEnhancementSubmitRequest,
    db: Db,
    settings: SettingsDep,
    gate: VideoCompositionEnhancementGateDep,
) -> VideoCompositionEnhancementSubmitRead:
    del gate
    return VideoCompositionEnhancementJobService(db, settings).enqueue(
        product_id, data
    )


@router.get(
    "/video-composition-enhancements/{enhancement_id}",
    response_model=VideoCompositionEnhancementRead,
)
def get_composition_enhancement(
    enhancement_id: int, db: Db, settings: SettingsDep
) -> VideoCompositionEnhancementRead:
    return VideoCompositionEnhancementService(db, settings).get(enhancement_id)


@router.get(
    "/video-composition-enhancement-artifacts/{artifact_id}",
    response_model=VideoCompositionEnhancementArtifactRead,
)
def get_composition_enhancement_artifact(
    artifact_id: int, db: Db, settings: SettingsDep
) -> VideoCompositionEnhancementArtifactRead:
    artifact, _ = VideoCompositionEnhancementArtifactAccessService(
        db, settings
    ).resolve_video(artifact_id)
    return VideoCompositionEnhancementArtifactRead.model_validate(artifact)


@router.get(
    "/video-composition-subtitle-artifacts/{artifact_id}",
    response_model=VideoCompositionSubtitleArtifactRead,
)
def get_composition_subtitle_artifact(
    artifact_id: int, db: Db, settings: SettingsDep
) -> VideoCompositionSubtitleArtifactRead:
    artifact, _ = VideoCompositionEnhancementArtifactAccessService(
        db, settings
    ).resolve_subtitle(artifact_id)
    return VideoCompositionSubtitleArtifactRead.model_validate(artifact)


def _asset_response(
    request: Request, path, length: int, content_type: str, filename: str
):
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": content_type,
        "Content-Disposition": f'inline; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    range_value = request.headers.get("range")
    if range_value is None:
        return StreamingResponse(
            stream_file(path), media_type=content_type, headers=headers
        )
    try:
        byte_range = parse_byte_range(range_value, length)
    except RangeNotSatisfiable:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{length}", "Content-Length": "0"},
        )
    headers["Content-Length"] = str(byte_range.length)
    headers["Content-Range"] = (
        f"bytes {byte_range.start}-{byte_range.end}/{length}"
    )
    return StreamingResponse(
        stream_file(path, start=byte_range.start, length=byte_range.length),
        status_code=206,
        media_type=content_type,
        headers=headers,
    )


@router.get("/video-composition-enhancement-artifacts/{artifact_id}/content")
def enhancement_content(
    artifact_id: int, request: Request, db: Db, settings: SettingsDep
):
    artifact, path = VideoCompositionEnhancementArtifactAccessService(
        db, settings
    ).resolve_video(artifact_id)
    return _asset_response(
        request,
        path,
        artifact.size_bytes,
        "video/mp4",
        f"enhancement-{artifact.enhancement_id}-{artifact.id}.mp4",
    )


@router.head("/video-composition-enhancement-artifacts/{artifact_id}/content")
def head_enhancement_content(
    artifact_id: int, db: Db, settings: SettingsDep
) -> Response:
    artifact, _ = VideoCompositionEnhancementArtifactAccessService(
        db, settings
    ).resolve_video(artifact_id)
    return Response(
        status_code=200,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(artifact.size_bytes),
            "Content-Type": "video/mp4",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/video-composition-subtitle-artifacts/{artifact_id}/content")
def subtitle_content(
    artifact_id: int, request: Request, db: Db, settings: SettingsDep
):
    artifact, path = VideoCompositionEnhancementArtifactAccessService(
        db, settings
    ).resolve_subtitle(artifact_id)
    return _asset_response(
        request,
        path,
        artifact.size_bytes,
        "text/vtt; charset=utf-8",
        f"enhancement-{artifact.enhancement_id}-subtitles.vtt",
    )


@router.head("/video-composition-subtitle-artifacts/{artifact_id}/content")
def head_subtitle_content(
    artifact_id: int, db: Db, settings: SettingsDep
) -> Response:
    try:
        artifact, _ = VideoCompositionEnhancementArtifactAccessService(
            db, settings
        ).resolve_subtitle(artifact_id)
    except AppError:
        raise AppError("Composition subtitle artifact not found", 404) from None
    return Response(
        status_code=200,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(artifact.size_bytes),
            "Content-Type": "text/vtt; charset=utf-8",
            "Content-Disposition": (
                'inline; filename="enhancement-'
                f'{artifact.enhancement_id}-subtitles.vtt"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
