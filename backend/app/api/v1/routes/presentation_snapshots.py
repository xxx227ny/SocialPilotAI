from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import (
    OptionalVideoArtifactStorageDep,
    VideoArtifactStorageDep,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.presentation_snapshot import (
    PresentationSnapshotCreate,
    PresentationSnapshotCreateRead,
    PresentationSnapshotRead,
)
from app.services.presentation_snapshot_service import (
    PresentationSnapshotService,
)
from app.services.video_artifact_http import (
    RangeNotSatisfiable,
    parse_byte_range,
    private_media_cache_headers,
    stream_file,
)
from app.services.video_preview import PREVIEW_VERSION, video_preview_path

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/products/{product_id}/presentation-snapshots",
    response_model=PresentationSnapshotCreateRead,
)
def create_presentation_snapshot(
    product_id: int,
    data: PresentationSnapshotCreate,
    db: DbSession,
    artifact_storage: OptionalVideoArtifactStorageDep,
) -> PresentationSnapshotCreateRead:
    return PresentationSnapshotService(db, artifact_storage).create(product_id, data)


@router.get(
    "/presentation-snapshots/{snapshot_id}",
    response_model=PresentationSnapshotRead,
)
def get_presentation_snapshot(
    snapshot_id: int,
    db: DbSession,
) -> PresentationSnapshotRead:
    return PresentationSnapshotService(db).get(snapshot_id)


@router.get(
    "/products/{product_id}/presentation-snapshots",
    response_model=list[PresentationSnapshotRead],
)
def list_presentation_snapshots(
    product_id: int,
    db: DbSession,
) -> list[PresentationSnapshotRead]:
    return PresentationSnapshotService(db).list_for_product(product_id)


def _snapshot_artifact_headers(
    snapshot_id: int,
    content_type: str,
    content_length: int,
    etag: str,
) -> dict[str, str]:
    extension = ".webm" if content_type == "video/webm" else ".mp4"
    return {
        "Accept-Ranges": "bytes",
        "Content-Disposition": (
            f'inline; filename="presentation-snapshot-{snapshot_id}{extension}"'
        ),
        "Content-Length": str(content_length),
        "Content-Type": content_type,
        "X-Content-Type-Options": "nosniff",
        **private_media_cache_headers(etag),
    }


@router.get("/presentation-snapshots/{snapshot_id}/artifact/content")
def get_presentation_snapshot_artifact_content(
    snapshot_id: int,
    request: Request,
    db: DbSession,
    artifact_storage: VideoArtifactStorageDep,
) -> Response:
    verified = PresentationSnapshotService(db, artifact_storage).resolve_artifact(
        snapshot_id
    )
    range_header = request.headers.get("range")
    if range_header is None:
        return StreamingResponse(
            stream_file(verified.path),
            status_code=200,
            headers=_snapshot_artifact_headers(
                snapshot_id,
                verified.content_type,
                verified.size_bytes,
                f"snapshot-source-{verified.sha256}",
            ),
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
                **private_media_cache_headers(f"snapshot-source-{verified.sha256}"),
            },
        )
    headers = _snapshot_artifact_headers(
        snapshot_id,
        verified.content_type,
        requested.length,
        f"snapshot-source-{verified.sha256}",
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


@router.head("/presentation-snapshots/{snapshot_id}/artifact/content")
def head_presentation_snapshot_artifact_content(
    snapshot_id: int,
    db: DbSession,
    artifact_storage: VideoArtifactStorageDep,
) -> Response:
    verified = PresentationSnapshotService(db, artifact_storage).resolve_artifact(
        snapshot_id
    )
    return Response(
        status_code=200,
        headers=_snapshot_artifact_headers(
            snapshot_id,
            verified.content_type,
            verified.size_bytes,
            f"snapshot-source-{verified.sha256}",
        ),
    )


@router.get("/presentation-snapshots/{snapshot_id}/artifact/preview")
def get_presentation_snapshot_artifact_preview(
    snapshot_id: int,
    request: Request,
    db: DbSession,
    artifact_storage: VideoArtifactStorageDep,
    settings: SettingsDep,
) -> Response:
    verified = PresentationSnapshotService(db, artifact_storage).resolve_artifact(
        snapshot_id
    )
    preview = video_preview_path(
        verified.path,
        verified.sha256,
        settings.video_composition_ffmpeg_path,
    )
    size_bytes = preview.stat().st_size
    etag = f"snapshot-preview-{PREVIEW_VERSION}-{verified.sha256}"
    range_header = request.headers.get("range")
    if range_header is None:
        return StreamingResponse(
            stream_file(preview),
            status_code=200,
            headers=_snapshot_artifact_headers(
                snapshot_id, "video/mp4", size_bytes, etag
            ),
            media_type="video/mp4",
        )
    try:
        requested = parse_byte_range(range_header, size_bytes)
    except RangeNotSatisfiable:
        return Response(
            status_code=416,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{size_bytes}",
                "Content-Length": "0",
                **private_media_cache_headers(etag),
            },
        )
    headers = _snapshot_artifact_headers(
        snapshot_id, "video/mp4", requested.length, etag
    )
    headers["Content-Range"] = f"bytes {requested.start}-{requested.end}/{size_bytes}"
    return StreamingResponse(
        stream_file(preview, start=requested.start, length=requested.length),
        status_code=206,
        headers=headers,
        media_type="video/mp4",
    )
