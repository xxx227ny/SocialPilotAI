from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import VideoRenderArtifact
from app.schemas.video_render_artifact import (
    VideoRenderArtifactCreate,
    VideoRenderArtifactSchema,
)
from app.services.video_artifact_storage import (
    LocalVideoArtifactStorage,
    VideoArtifactError,
)
from app.services.video_render_service import VideoRenderService
from tests.test_video_render_service import create_video_project, render_request


def create_succeeded_render_task(db_session: Session):
    project = create_video_project(db_session)
    service = VideoRenderService(db_session)
    task = service.create_render_task(project.id, render_request())
    service.transition_status(task.id, "SUBMITTED")
    return service.transition_status(task.id, "SUCCEEDED")


def artifact_data(
    *, storage_path: str = "oss://socialpilot/render-task-001.mp4"
) -> VideoRenderArtifactCreate:
    return VideoRenderArtifactCreate(
        provider_output_url="https://provider.example/result.mp4",
        storage_path=storage_path,
        metadata={
            "duration": 4,
            "ratio": "9:16",
            "resolution": "720P",
        },
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )


def test_artifact_is_created_for_succeeded_task(db_session: Session) -> None:
    task = create_succeeded_render_task(db_session)

    artifact = VideoRenderService(db_session).save_artifact(task.id, artifact_data())

    assert artifact.id is not None
    assert artifact.video_render_task_id == task.id
    assert artifact.provider_output_url == "https://provider.example/result.mp4"
    assert artifact.storage_path == "oss://socialpilot/render-task-001.mp4"


def test_artifact_relationship_points_to_render_task(
    db_session: Session,
) -> None:
    task = create_succeeded_render_task(db_session)
    artifact = VideoRenderService(db_session).save_artifact(task.id, artifact_data())

    assert artifact.video_render_task.id == task.id
    assert task.artifact is artifact


def test_artifact_metadata_is_stored_and_serialized(
    db_session: Session,
) -> None:
    task = create_succeeded_render_task(db_session)
    artifact = VideoRenderService(db_session).save_artifact(task.id, artifact_data())

    response = VideoRenderArtifactSchema.model_validate(artifact)

    assert response.metadata == {
        "duration": 4,
        "ratio": "9:16",
        "resolution": "720P",
    }
    assert response.expires_at is not None


def test_artifact_can_be_queried_and_updated(db_session: Session) -> None:
    task = create_succeeded_render_task(db_session)
    service = VideoRenderService(db_session)
    created = service.save_artifact(task.id, artifact_data())

    fetched = service.get_artifact(task.id)
    updated = service.save_artifact(
        task.id,
        artifact_data(storage_path="oss://socialpilot/permanent/render.mp4"),
    )

    assert fetched.id == created.id
    assert updated.id == created.id
    assert updated.storage_path == "oss://socialpilot/permanent/render.mp4"
    assert service.list_artifacts() == [updated]
    assert db_session.scalar(select(func.count()).select_from(VideoRenderArtifact)) == 1


def test_missing_artifact_returns_not_found(db_session: Session) -> None:
    project = create_video_project(db_session)
    service = VideoRenderService(db_session)
    task = service.create_render_task(project.id, render_request())

    try:
        service.get_artifact(task.id)
    except AppError as exc:
        assert exc.status_code == 404
        assert exc.message == "Video render artifact not found"
    else:
        raise AssertionError("missing render artifact should fail")


def test_artifact_requires_succeeded_task(db_session: Session) -> None:
    project = create_video_project(db_session)
    service = VideoRenderService(db_session)
    task = service.create_render_task(project.id, render_request())

    try:
        service.save_artifact(task.id, artifact_data())
    except AppError as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("unfinished render task should reject artifacts")


def test_render_task_status_transitions_are_guarded(
    db_session: Session,
) -> None:
    project = create_video_project(db_session)
    service = VideoRenderService(db_session)
    task = service.create_render_task(project.id, render_request())

    try:
        service.transition_status(task.id, "SUCCEEDED")
    except AppError as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("invalid render task transition should fail")

    submitted = service.transition_status(task.id, "SUBMITTED")
    assert submitted.status == "SUBMITTED"

    try:
        service.transition_status(task.id, "FAILED")
    except AppError as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("failed status should require an error code")

    failed = service.transition_status(
        task.id,
        "FAILED",
        error_code="PROVIDER_ERROR",
        error_message="Safe provider error summary",
    )
    assert failed.status == "FAILED"
    assert failed.error_code == "PROVIDER_ERROR"


def test_quicktime_mov_storage_and_safe_resolution(tmp_path: Path) -> None:
    storage = LocalVideoArtifactStorage(tmp_path.resolve(), 1024)
    stored = storage.store(
        task_id=41, content=b"fake-quicktime-bytes", content_type="video/quicktime"
    )

    assert stored.relative_path.endswith(".mov")
    assert stored.content_type == "video/quicktime"
    resolved, resolved_type = storage.resolve(stored.relative_path)
    assert resolved.read_bytes() == b"fake-quicktime-bytes"
    assert resolved_type == "video/quicktime"

    for unsafe in ("../escape.mov", stored.relative_path.replace(".mov", ".mp4")):
        with pytest.raises(VideoArtifactError):
            storage.resolve(unsafe)
    with pytest.raises(VideoArtifactError):
        storage.store(task_id=42, content=b"fake", content_type="video/mov")
