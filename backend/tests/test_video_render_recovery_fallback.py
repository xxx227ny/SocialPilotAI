from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_visual_generation_provider
from app.core.config import get_settings
from app.main import app
from app.models import VideoRenderArtifact, VideoRenderTask
from app.repositories.video_render_artifact_repository import (
    VideoRenderArtifactRepository,
)
from app.schemas.video_render import VideoRenderTaskCreate
from app.schemas.video_render_artifact import VideoRenderArtifactCreate
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from app.services.video_render_operation_service import (
    VideoProjectRenderExecutionService,
)
from app.services.video_render_service import VideoRenderService
from tests.test_video_render_contract import (
    contract_settings,
    count_rows,
    execute_path,
    install_contract_dependencies,
    latest_path,
)
from tests.test_video_render_execution_service import (
    FakeOutputFetcher,
    MockVisualProvider,
)
from tests.test_video_render_service import create_video_project


def create_task(
    db_session: Session,
    project_id: int,
    *,
    status: str,
    idempotency_key: str,
) -> VideoRenderTask:
    task = VideoRenderService(db_session).create_render_task(
        project_id,
        VideoRenderTaskCreate(
            scene_sequence=1,
            resolution="720P",
            idempotency_key=idempotency_key,
        ),
    )
    task.status = status
    if status not in {"CREATED", "SUBMITTING", "SUBMIT_UNKNOWN"}:
        task.provider_name = "Wanx"
        task.provider_task_id = "safe-fake-provider-task"
    if status in {"FAILED", "CANCELED", "ARTIFACT_PERSIST_FAILED"}:
        task.error_code = "safe_test_failure"
        task.error_message = "Safe recovery guidance"
    db_session.commit()
    db_session.refresh(task)
    return task


def install_read_only_dependencies(
    tmp_path: Path,
    provider_counter: list[int],
) -> None:
    app.dependency_overrides[get_settings] = lambda: contract_settings(
        tmp_path, enabled=False
    )

    def forbidden_provider():
        provider_counter[0] += 1
        raise AssertionError("read-only recovery resolved a Provider")

    app.dependency_overrides[get_visual_generation_provider] = (
        forbidden_provider
    )


@pytest.mark.parametrize(
    (
        "status",
        "category",
        "continue_allowed",
        "refresh_allowed",
        "resubmit_forbidden",
    ),
    [
        ("CREATED", "created", True, False, False),
        ("SUBMITTING", "submit_uncertain", False, False, True),
        ("SUBMIT_UNKNOWN", "submit_uncertain", False, False, True),
        ("SUBMITTED", "active", False, True, True),
        ("PENDING", "active", False, True, True),
        ("RUNNING", "active", False, True, True),
        ("REFRESHING", "refresh_uncertain", False, False, True),
        ("FAILED", "terminal_failure", False, False, True),
        ("CANCELED", "terminal_failure", False, False, True),
        (
            "ARTIFACT_PERSIST_FAILED",
            "artifact_persist_failed",
            False,
            False,
            True,
        ),
    ],
)
def test_latest_recovery_returns_authoritative_safe_decision_without_writes(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    status: str,
    category: str,
    continue_allowed: bool,
    refresh_allowed: bool,
    resubmit_forbidden: bool,
) -> None:
    project = create_video_project(db_session)
    task = create_task(
        db_session,
        project.id,
        status=status,
        idempotency_key=f"recovery-matrix-{status}",
    )
    original_updated_at = task.updated_at
    provider_counter = [0]
    install_read_only_dependencies(tmp_path, provider_counter)

    response = client.get(latest_path(project.id))

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["id"] == task.id
    assert body["recovered"] is True
    assert body["external_call"] is False
    assert body["recovery"] == {
        "category": category,
        "artifact_state": "not_applicable",
        "read_only_retry_allowed": True,
        "continue_original_submit_allowed": continue_allowed,
        "explicit_refresh_allowed": refresh_allowed,
        "resubmit_forbidden": resubmit_forbidden,
        "presentation_fallback_available": True,
        "automatic_action_allowed": False,
        "user_message": body["recovery"]["user_message"],
    }
    assert body["recovery"]["user_message"]
    serialized = response.text.casefold()
    assert "provider_task_id" not in serialized
    assert "provider_output_url" not in serialized
    assert "storage_path" not in serialized
    assert str(tmp_path.resolve()).casefold() not in serialized
    assert provider_counter == [0]
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == 0
    db_session.refresh(task)
    assert task.updated_at == original_updated_at


def test_recovery_without_task_is_read_only_404(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    provider_counter = [0]
    install_read_only_dependencies(tmp_path, provider_counter)

    response = client.get(latest_path(project.id))

    assert response.status_code == 404
    assert provider_counter == [0]
    assert count_rows(db_session, VideoRenderTask) == 0
    assert count_rows(db_session, VideoRenderArtifact) == 0


def test_created_recovery_continues_same_original_task_once(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    provider = MockVisualProvider()
    settings = contract_settings(tmp_path)
    storage = LocalVideoArtifactStorage(tmp_path.resolve(), 1_000_000)
    operation_service = VideoProjectRenderExecutionService(
        db_session,
        provider,
        settings,
        FakeOutputFetcher(),
        storage,
    )
    original = create_task(
        db_session,
        project.id,
        status="CREATED",
        idempotency_key=operation_service._idempotency_key(project),
    )
    install_contract_dependencies(tmp_path, provider)

    first = client.post(execute_path(project.id))
    second = client.post(execute_path(project.id))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["task"]["id"] == original.id
    assert second.json()["task"]["id"] == original.id
    assert first.json()["task"]["status"] == "PENDING"
    assert second.json()["reused"] is True
    assert second.json()["external_call"] is False
    assert provider.submit_calls == 1
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == 0


@pytest.mark.parametrize(
    "status",
    [
        "SUBMITTING",
        "SUBMIT_UNKNOWN",
        "SUBMITTED",
        "PENDING",
        "RUNNING",
        "REFRESHING",
        "FAILED",
        "CANCELED",
        "ARTIFACT_PERSIST_FAILED",
    ],
)
def test_existing_non_created_task_cannot_be_resubmitted(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    status: str,
) -> None:
    project = create_video_project(db_session)
    provider = MockVisualProvider()
    settings = contract_settings(tmp_path)
    service = VideoProjectRenderExecutionService(
        db_session,
        provider,
        settings,
        FakeOutputFetcher(),
        LocalVideoArtifactStorage(tmp_path.resolve(), 1_000_000),
    )
    task = create_task(
        db_session,
        project.id,
        status=status,
        idempotency_key=service._idempotency_key(project),
    )
    install_contract_dependencies(tmp_path, provider)

    response = client.post(execute_path(project.id))

    assert response.status_code == 200
    assert response.json()["task"]["id"] == task.id
    assert response.json()["task"]["status"] == status
    assert response.json()["external_call"] is False
    assert response.json()["reused"] is True
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0
    assert count_rows(db_session, VideoRenderTask) == 1


def test_refreshing_recovery_blocks_parallel_refresh(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    task = create_task(
        db_session,
        project.id,
        status="REFRESHING",
        idempotency_key="refresh-in-progress",
    )
    provider = MockVisualProvider()
    install_contract_dependencies(tmp_path, provider)

    response = client.post(
        f"/api/v1/video-render-tasks/{task.id}/refresh"
    )

    assert response.status_code == 409
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == 0


def save_artifact(
    db_session: Session,
    task: VideoRenderTask,
    *,
    storage_path: str | None,
    metadata: dict[str, object],
) -> VideoRenderArtifact:
    return VideoRenderArtifactRepository(db_session).create(
        task.id,
        VideoRenderArtifactCreate(
            provider_output_url="https://safe-test.invalid/video.mp4",
            storage_path=storage_path,
            metadata=metadata,
        ),
    )


def create_exact_workspace_task(
    db_session: Session,
    tmp_path: Path,
    *,
    status: str,
) -> tuple[VideoRenderTask, MockVisualProvider, FakeOutputFetcher]:
    project = create_video_project(db_session)
    provider = MockVisualProvider()
    fetcher = FakeOutputFetcher()
    operation_service = VideoProjectRenderExecutionService(
        db_session,
        provider,
        contract_settings(tmp_path),
        fetcher,
        LocalVideoArtifactStorage(tmp_path.resolve(), 1_000_000),
    )
    task = create_task(
        db_session,
        project.id,
        status=status,
        idempotency_key=operation_service._idempotency_key(project),
    )
    install_contract_dependencies(
        tmp_path,
        provider,
        fetcher=fetcher,
    )
    return task, provider, fetcher


def get_all_operation_responses(
    client: TestClient,
    task: VideoRenderTask,
) -> list:
    return [
        client.post(execute_path(task.video_project_id)),
        client.get(latest_path(task.video_project_id)),
        client.get(f"/api/v1/video-render-tasks/{task.id}/recovery"),
    ]


def assert_consistent_recovery(
    responses: list,
    *,
    category: str,
    artifact_state: str,
) -> None:
    for response in responses:
        assert response.status_code == 200
        body = response.json()
        assert body["recovery"]["category"] == category
        assert body["recovery"]["artifact_state"] == artifact_state
        assert body["external_call"] is False
        assert "provider_task_id" not in response.text
        assert "provider_output_url" not in response.text
        assert "storage_path" not in response.text


def test_succeeded_recovery_reports_verified_local_artifact(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    task = create_task(
        db_session,
        project.id,
        status="SUCCEEDED",
        idempotency_key="succeeded-available",
    )
    content = b"safe-recovery-video"
    filename = "safe-recovery.mp4"
    (tmp_path / filename).write_bytes(content)
    artifact = save_artifact(
        db_session,
        task,
        storage_path=filename,
        metadata={
            "content_type": "video/mp4",
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    )
    provider_counter = [0]
    install_read_only_dependencies(tmp_path, provider_counter)

    latest = client.get(latest_path(project.id))
    exact = client.get(
        f"/api/v1/video-render-tasks/{task.id}/recovery"
    )

    for response in (latest, exact):
        assert response.status_code == 200
        body = response.json()
        assert body["task"]["id"] == task.id
        assert body["artifact"]["id"] == artifact.id
        assert body["recovery"]["category"] == "succeeded"
        assert body["recovery"]["artifact_state"] == "available"
        assert body["recovery"]["explicit_refresh_allowed"] is False
        assert body["recovery"]["automatic_action_allowed"] is False
        assert "provider_output_url" not in response.text
        assert "storage_path" not in response.text
    assert provider_counter == [0]
    assert count_rows(db_session, VideoRenderArtifact) == 1


def test_succeeded_artifact_decision_is_consistent_across_all_operations(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    task, provider, fetcher = create_exact_workspace_task(
        db_session,
        tmp_path,
        status="SUCCEEDED",
    )
    content = b"safe-consistent-video"
    filename = "safe-consistent.mp4"
    (tmp_path / filename).write_bytes(content)
    artifact = save_artifact(
        db_session,
        task,
        storage_path=filename,
        metadata={
            "content_type": "video/mp4",
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    )
    task_updated_at = task.updated_at
    artifact_updated_at = artifact.updated_at

    responses = get_all_operation_responses(client, task)

    assert_consistent_recovery(
        responses,
        category="succeeded",
        artifact_state="available",
    )
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0
    assert fetcher.calls == 0
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == 1
    db_session.refresh(task)
    db_session.refresh(artifact)
    assert task.updated_at == task_updated_at
    assert artifact.updated_at == artifact_updated_at


def test_missing_artifact_file_is_consistent_across_all_operations(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    task, provider, fetcher = create_exact_workspace_task(
        db_session,
        tmp_path,
        status="SUCCEEDED",
    )
    artifact = save_artifact(
        db_session,
        task,
        storage_path="missing-consistency.mp4",
        metadata={
            "content_type": "video/mp4",
            "size_bytes": 4,
            "sha256": "0" * 64,
        },
    )
    task_updated_at = task.updated_at
    artifact_updated_at = artifact.updated_at

    responses = get_all_operation_responses(client, task)

    assert_consistent_recovery(
        responses,
        category="succeeded_artifact_unavailable",
        artifact_state="missing",
    )
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0
    assert fetcher.calls == 0
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == 1
    db_session.refresh(task)
    db_session.refresh(artifact)
    assert task.updated_at == task_updated_at
    assert artifact.updated_at == artifact_updated_at


@pytest.mark.parametrize(
    ("storage_path", "metadata", "expected_state"),
    [
        (
            "invalid-size.mp4",
            {
                "content_type": "video/mp4",
                "size_bytes": 999,
                "sha256": hashlib.sha256(b"safe").hexdigest(),
            },
            "invalid",
        ),
        (
            "invalid-type.mp4",
            {
                "content_type": "video/webm",
                "size_bytes": 4,
                "sha256": hashlib.sha256(b"safe").hexdigest(),
            },
            "invalid",
        ),
        (
            "invalid-metadata.mp4",
            {
                "content_type": "video/mp4",
                "size_bytes": 4,
                "sha256": "not-a-hash",
            },
            "invalid",
        ),
        (
            "../outside-consistency.mp4",
            {
                "content_type": "video/mp4",
                "size_bytes": 4,
                "sha256": hashlib.sha256(b"safe").hexdigest(),
            },
            "missing",
        ),
    ],
)
def test_invalid_artifact_decision_is_consistent_across_all_operations(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    storage_path: str,
    metadata: dict[str, object],
    expected_state: str,
) -> None:
    task, provider, fetcher = create_exact_workspace_task(
        db_session,
        tmp_path,
        status="SUCCEEDED",
    )
    if "/" not in storage_path and "\\" not in storage_path:
        (tmp_path / storage_path).write_bytes(b"safe")
    artifact = save_artifact(
        db_session,
        task,
        storage_path=storage_path,
        metadata=metadata,
    )
    task_updated_at = task.updated_at
    artifact_updated_at = artifact.updated_at

    responses = get_all_operation_responses(client, task)

    assert_consistent_recovery(
        responses,
        category="succeeded_artifact_unavailable",
        artifact_state=expected_state,
    )
    serialized = "".join(response.text for response in responses)
    assert storage_path not in serialized
    assert str(tmp_path.resolve()) not in serialized
    assert "integrity metadata" not in serialized.casefold()
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0
    assert fetcher.calls == 0
    db_session.refresh(task)
    db_session.refresh(artifact)
    assert task.updated_at == task_updated_at
    assert artifact.updated_at == artifact_updated_at


def test_created_with_provider_identity_fails_closed(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    task, provider, fetcher = create_exact_workspace_task(
        db_session,
        tmp_path,
        status="CREATED",
    )
    task.provider_name = "Wanx"
    task.provider_task_id = "unexpected-existing-provider-task"
    db_session.commit()

    responses = get_all_operation_responses(client, task)

    for response in responses:
        assert response.status_code == 200
        decision = response.json()["recovery"]
        assert decision["category"] == "submit_uncertain"
        assert decision["continue_original_submit_allowed"] is False
        assert decision["explicit_refresh_allowed"] is False
        assert decision["resubmit_forbidden"] is True
        assert response.json()["external_call"] is False
        assert "unexpected-existing-provider-task" not in response.text
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0
    assert fetcher.calls == 0
    assert count_rows(db_session, VideoRenderTask) == 1


@pytest.mark.parametrize("status", ["SUBMITTED", "PENDING", "RUNNING"])
def test_active_without_provider_identity_cannot_refresh(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    status: str,
) -> None:
    task, provider, fetcher = create_exact_workspace_task(
        db_session,
        tmp_path,
        status=status,
    )
    task.provider_task_id = None
    db_session.commit()

    execution, latest, exact = get_all_operation_responses(client, task)
    refresh = client.post(
        f"/api/v1/video-render-tasks/{task.id}/refresh"
    )

    assert_consistent_recovery(
        [execution, latest, exact],
        category="refresh_uncertain",
        artifact_state="not_applicable",
    )
    for response in (execution, latest, exact):
        decision = response.json()["recovery"]
        assert decision["explicit_refresh_allowed"] is False
        assert decision["resubmit_forbidden"] is True
    assert refresh.status_code == 409
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0
    assert fetcher.calls == 0
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == 0


@pytest.mark.parametrize(
    ("storage_path", "metadata", "expected_state"),
    [
        (None, {}, "missing"),
        (
            "missing.mp4",
            {
                "content_type": "video/mp4",
                "size_bytes": 4,
                "sha256": "0" * 64,
            },
            "missing",
        ),
        (
            "../outside.mp4",
            {
                "content_type": "video/mp4",
                "size_bytes": 4,
                "sha256": "0" * 64,
            },
            "missing",
        ),
        (
            "invalid-metadata.mp4",
            {
                "content_type": "video/mp4",
                "size_bytes": 999,
                "sha256": "not-a-hash",
            },
            "invalid",
        ),
    ],
)
def test_succeeded_recovery_reports_unavailable_artifact_without_provider(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    storage_path: str | None,
    metadata: dict[str, object],
    expected_state: str,
) -> None:
    project = create_video_project(db_session)
    task = create_task(
        db_session,
        project.id,
        status="SUCCEEDED",
        idempotency_key=f"succeeded-{expected_state}-{storage_path}",
    )
    if storage_path == "invalid-metadata.mp4":
        (tmp_path / storage_path).write_bytes(b"safe")
    if storage_path is not None:
        save_artifact(
            db_session,
            task,
            storage_path=storage_path,
            metadata=metadata,
        )
    provider_counter = [0]
    install_read_only_dependencies(tmp_path, provider_counter)

    response = client.get(latest_path(project.id))

    assert response.status_code == 200
    decision = response.json()["recovery"]
    assert decision["category"] == "succeeded_artifact_unavailable"
    assert decision["artifact_state"] == expected_state
    assert decision["read_only_retry_allowed"] is True
    assert decision["presentation_fallback_available"] is True
    assert decision["explicit_refresh_allowed"] is False
    assert decision["resubmit_forbidden"] is True
    assert decision["automatic_action_allowed"] is False
    assert provider_counter == [0]
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == (
        0 if storage_path is None else 1
    )
