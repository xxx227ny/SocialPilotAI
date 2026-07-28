from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import get_video_artifact_storage
from app.main import app
from app.models import VideoRenderArtifact
from app.schemas.video_render import VideoRenderTaskCreate
from app.schemas.video_render_artifact import VideoRenderArtifactCreate
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from app.services.video_render_service import VideoRenderService
from tests.test_video_render_service import create_video_project

CONTENT = bytes(range(256)) * 8


def prepare_artifact(
    db_session: Session,
    tmp_path: Path,
) -> tuple[VideoRenderArtifact, Path]:
    project = create_video_project(db_session)
    service = VideoRenderService(db_session)
    task = service.create_render_task(
        project.id,
        VideoRenderTaskCreate(
            scene_sequence=1,
            resolution="720P",
            idempotency_key=f"artifact-delivery-{project.id}",
        ),
    )
    task.provider_name = "Wanx"
    task.provider_task_id = "provider-secret-task-id"
    service.transition_status(task.id, "SUBMITTED")
    service.transition_status(task.id, "SUCCEEDED")
    storage_root = tmp_path / "artifacts"
    storage_root.mkdir()
    path = storage_root / "verified.mp4"
    path.write_bytes(CONTENT)
    artifact = service.save_artifact(
        task.id,
        VideoRenderArtifactCreate(
            provider_output_url=(
                "https://provider.invalid/private.mp4"
            ),
            storage_path=path.name,
            metadata={
                "content_type": "video/mp4",
                "size_bytes": len(CONTENT),
                "sha256": hashlib.sha256(CONTENT).hexdigest(),
            },
        ),
    )
    app.dependency_overrides[get_video_artifact_storage] = lambda: (
        LocalVideoArtifactStorage(storage_root.resolve(), 10_000)
    )
    return artifact, path


def metadata_path(artifact_id: int) -> str:
    return f"/api/v1/video-render-artifacts/{artifact_id}"


def content_path(artifact_id: int) -> str:
    return f"{metadata_path(artifact_id)}/content"


def download_path(artifact_id: int) -> str:
    return f"{metadata_path(artifact_id)}/download"


def test_metadata_is_safe_and_verified(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    artifact, _ = prepare_artifact(db_session, tmp_path)

    response = client.get(metadata_path(artifact.id))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": artifact.id,
        "video_render_task_id": artifact.video_render_task_id,
        "provider": "Wanx",
        "content_available": True,
        "content_url": content_path(artifact.id),
        "download_url": download_path(artifact.id),
        "content_type": "video/mp4",
        "size_bytes": len(CONTENT),
        "sha256": hashlib.sha256(CONTENT).hexdigest(),
        "storage_kind": "local_filesystem",
        "created_at": body["created_at"],
        "updated_at": body["updated_at"],
    }
    serialized = response.text.casefold()
    for forbidden in (
        "storage_path",
        "provider_output_url",
        "provider_task_id",
        "provider.invalid",
        str(tmp_path).casefold(),
    ):
        assert forbidden not in serialized


def test_full_get_and_head_headers(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    artifact, _ = prepare_artifact(db_session, tmp_path)

    response = client.get(content_path(artifact.id))
    head = client.head(content_path(artifact.id))

    assert response.status_code == 200
    assert response.content == CONTENT
    for result in (response, head):
        assert result.headers["content-type"] == "video/mp4"
        assert result.headers["content-length"] == str(len(CONTENT))
        assert result.headers["accept-ranges"] == "bytes"
        assert result.headers["content-disposition"].startswith("inline;")
    assert head.status_code == 200
    assert head.content == b""


@pytest.mark.parametrize(
    ("value", "expected", "content_range"),
    [
        ("bytes=0-99", CONTENT[0:100], f"bytes 0-99/{len(CONTENT)}"),
        ("bytes=100-", CONTENT[100:], f"bytes 100-2047/{len(CONTENT)}"),
        ("bytes=-100", CONTENT[-100:], f"bytes 1948-2047/{len(CONTENT)}"),
        ("bytes=777-777", CONTENT[777:778], f"bytes 777-777/{len(CONTENT)}"),
    ],
)
def test_supported_ranges(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    value: str,
    expected: bytes,
    content_range: str,
) -> None:
    artifact, _ = prepare_artifact(db_session, tmp_path)

    response = client.get(
        content_path(artifact.id),
        headers={"Range": value},
    )

    assert response.status_code == 206
    assert response.content == expected
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(expected))
    assert response.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize(
    "value",
    [
        "bytes=9999-",
        "bytes=100-99",
        "bytes=",
        "bytes=0-1,3-4",
        "items=0-1",
        "bytes=-0",
        "bytes=abc-def",
    ],
)
def test_invalid_ranges_return_416(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    value: str,
) -> None:
    artifact, _ = prepare_artifact(db_session, tmp_path)

    response = client.get(
        content_path(artifact.id),
        headers={"Range": value},
    )

    assert response.status_code == 416
    assert response.content == b""
    assert response.headers["content-range"] == f"bytes */{len(CONTENT)}"


def test_download_is_safe_attachment_with_identical_bytes(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    artifact, _ = prepare_artifact(db_session, tmp_path)

    response = client.get(download_path(artifact.id))

    assert response.status_code == 200
    assert response.content == CONTENT
    assert response.headers["content-length"] == str(len(CONTENT))
    assert response.headers["content-type"] == "video/mp4"
    disposition = response.headers["content-disposition"]
    assert disposition == (
        f'attachment; filename="video-artifact-{artifact.id}-task-'
        f'{artifact.video_render_task_id}.mp4"'
    )
    assert "/" not in disposition and "\\" not in disposition


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.mp4",
        "folder/video.mp4",
        "C:/private/video.mp4",
    ],
)
def test_unsafe_storage_paths_are_rejected(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    artifact, _ = prepare_artifact(db_session, tmp_path)
    artifact.storage_path = unsafe_path
    db_session.commit()

    response = client.get(content_path(artifact.id))

    assert response.status_code == 404
    assert str(tmp_path).casefold() not in response.text.casefold()


def test_symlink_escape_is_rejected_when_supported(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    artifact, path = prepare_artifact(db_session, tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(CONTENT)
    path.unlink()
    try:
        os.symlink(outside, path)
    except OSError as exc:
        pytest.skip(f"symbolic links are unavailable on this Windows host: {exc}")

    response = client.get(content_path(artifact.id))

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("mutation", "status_code"),
    [
        ("missing", 404),
        ("directory", 404),
        ("unsupported", 404),
        ("size", 409),
        ("content_type", 409),
        ("sha256", 409),
        ("task_status", 409),
        ("orphan_task", 409),
    ],
)
def test_integrity_and_task_state_fail_closed(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    mutation: str,
    status_code: int,
) -> None:
    artifact, path = prepare_artifact(db_session, tmp_path)
    if mutation == "missing":
        path.unlink()
    elif mutation == "directory":
        path.unlink()
        path.mkdir()
    elif mutation == "unsupported":
        unsupported = path.with_suffix(".txt")
        path.rename(unsupported)
        artifact.storage_path = unsupported.name
    elif mutation == "size":
        artifact.artifact_metadata = {
            **artifact.artifact_metadata,
            "size_bytes": len(CONTENT) + 1,
        }
    elif mutation == "content_type":
        artifact.artifact_metadata = {
            **artifact.artifact_metadata,
            "content_type": "video/webm",
        }
    elif mutation == "sha256":
        artifact.artifact_metadata = {
            **artifact.artifact_metadata,
            "sha256": "not-a-sha",
        }
    elif mutation == "task_status":
        artifact.video_render_task.status = "FAILED"
    else:
        db_session.execute(
            update(VideoRenderArtifact)
            .where(VideoRenderArtifact.id == artifact.id)
            .values(video_render_task_id=999_999)
        )
    db_session.commit()
    db_session.expire_all()

    response = client.get(content_path(artifact.id))

    assert response.status_code == status_code
    assert "provider.invalid" not in response.text
    assert str(tmp_path).casefold() not in response.text.casefold()


def test_content_download_and_recovery_are_read_only_and_safe(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    artifact, _ = prepare_artifact(db_session, tmp_path)
    count_before = int(
        db_session.scalar(
            select(func.count()).select_from(VideoRenderArtifact)
        )
        or 0
    )
    updated_before = artifact.updated_at

    content = client.get(content_path(artifact.id))
    download = client.get(download_path(artifact.id))
    recovery = client.get(
        f"/api/v1/video-render-tasks/"
        f"{artifact.video_render_task_id}/recovery"
    )

    assert content.status_code == download.status_code == 200
    assert recovery.status_code == 200
    recovery_body = recovery.json()
    assert recovery_body["artifact"]["id"] == artifact.id
    assert "provider_task_id" not in recovery.text
    assert "content_url" not in recovery.text
    db_session.expire_all()
    reloaded = db_session.get(VideoRenderArtifact, artifact.id)
    assert reloaded is not None and reloaded.updated_at == updated_before
    assert (
        db_session.scalar(
            select(func.count()).select_from(VideoRenderArtifact)
        )
        == count_before
    )
