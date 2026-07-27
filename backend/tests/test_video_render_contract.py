from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_provider_output_fetcher,
    get_video_artifact_storage,
    get_visual_generation_provider,
)
from app.core.config import Settings, get_settings
from app.main import app
from app.models import VideoRenderArtifact, VideoRenderTask
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderModelError,
    ProviderQuotaError,
    ProviderTimeoutError,
)
from app.providers.visual_base import VisualTaskSnapshot
from app.schemas.video_render import VideoRenderTaskCreate
from app.schemas.video_render_artifact import VideoRenderArtifactCreate
from app.services.video_artifact_storage import (
    LocalVideoArtifactStorage,
    VideoArtifactError,
    VideoArtifactStorage,
)
from app.services.video_render_service import VideoRenderService
from tests.test_video_render_execution_service import (
    FakeOutputFetcher,
    MockVisualProvider,
)
from tests.test_video_render_service import create_video_project


def contract_settings(
    artifact_root: Path,
    *,
    enabled: bool = True,
) -> Settings:
    return Settings(
        _env_file=None,
        enable_video_render_execution=enabled,
        wanx_api_key="safe-test-placeholder",
        wanx_endpoint="https://safe-test.invalid",
        video_artifact_storage_root=str(artifact_root.resolve()),
        video_artifact_max_bytes=1_000_000,
    )


def install_contract_dependencies(
    artifact_root: Path,
    provider: MockVisualProvider,
    *,
    fetcher: FakeOutputFetcher | None = None,
    enabled: bool = True,
    storage: VideoArtifactStorage | None = None,
) -> FakeOutputFetcher:
    selected_fetcher = fetcher or FakeOutputFetcher()
    selected_storage = storage or LocalVideoArtifactStorage(
        artifact_root.resolve(), 1_000_000
    )
    app.dependency_overrides[get_settings] = lambda: contract_settings(
        artifact_root, enabled=enabled
    )
    app.dependency_overrides[get_visual_generation_provider] = lambda: provider
    app.dependency_overrides[get_provider_output_fetcher] = (
        lambda: selected_fetcher
    )
    app.dependency_overrides[get_video_artifact_storage] = (
        lambda: selected_storage
    )
    return selected_fetcher


def count_rows(db_session: Session, model: type) -> int:
    return int(
        db_session.scalar(select(func.count()).select_from(model)) or 0
    )


def execute_path(project_id: int) -> str:
    return f"/api/v1/video-projects/{project_id}/render-execution"


def latest_path(project_id: int) -> str:
    return f"/api/v1/video-projects/{project_id}/render-tasks/latest"


def test_default_gate_stops_before_provider_and_task_write(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    provider_resolutions = 0

    def forbidden_provider():
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("disabled execution resolved a Provider")

    app.dependency_overrides[get_settings] = lambda: contract_settings(
        tmp_path, enabled=False
    )
    app.dependency_overrides[get_visual_generation_provider] = forbidden_provider

    response = client.post(execute_path(project.id))

    assert response.status_code == 503
    assert provider_resolutions == 0
    assert count_rows(db_session, VideoRenderTask) == 0
    assert count_rows(db_session, VideoRenderArtifact) == 0


def test_exact_execution_is_idempotent_and_safe(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    provider = MockVisualProvider()
    install_contract_dependencies(tmp_path, provider)

    first = client.post(execute_path(project.id))
    repeated = client.post(execute_path(project.id))

    assert first.status_code == 200
    assert repeated.status_code == 200
    first_body = first.json()
    repeated_body = repeated.json()
    assert first_body["video_project_id"] == project.id
    assert first_body["product_id"] == project.product_id
    assert first_body["marketing_strategy_id"] == project.marketing_strategy_id
    assert first_body["copy_matrix_id"] == project.copy_matrix_id
    assert first_body["task"]["scene_sequence"] == 1
    assert first_body["task"]["resolution"] == "720P"
    assert first_body["task"]["status"] == "PENDING"
    assert first_body["external_call"] is True
    assert first_body["reused"] is False
    assert repeated_body["task"]["id"] == first_body["task"]["id"]
    assert repeated_body["external_call"] is False
    assert repeated_body["reused"] is True
    assert provider.submit_calls == 1
    assert count_rows(db_session, VideoRenderTask) == 1
    serialized = first.text.casefold()
    assert "render_prompt" not in serialized
    assert "idempotency_key" not in serialized
    assert "storage_path" not in serialized
    assert "provider_output_url" not in serialized
    assert "marketingbrief" in serialized


def test_execution_rejects_cross_product_associations_without_submit(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    other = create_video_project(db_session)
    project.marketing_strategy_id = other.marketing_strategy_id
    db_session.commit()
    provider = MockVisualProvider()
    install_contract_dependencies(tmp_path, provider)

    response = client.post(execute_path(project.id))

    assert response.status_code == 422
    assert provider.submit_calls == 0
    assert count_rows(db_session, VideoRenderTask) == 0


@pytest.mark.parametrize(
    ("provider_error", "status_code", "error_code"),
    [
        (ProviderAuthenticationError("secret"), 502, "authentication"),
        (ProviderQuotaError("secret"), 429, "quota_or_rate_limit"),
        (ProviderModelError("secret"), 502, "invalid_provider_output"),
    ],
)
def test_definite_submit_failures_are_safe_and_terminal(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    provider_error: Exception,
    status_code: int,
    error_code: str,
) -> None:
    project = create_video_project(db_session)
    provider = MockVisualProvider(submit_error=provider_error)
    install_contract_dependencies(tmp_path, provider)

    response = client.post(execute_path(project.id))
    recovered = client.get(latest_path(project.id))

    assert response.status_code == status_code
    assert "secret" not in response.text
    assert recovered.status_code == 200
    assert recovered.json()["task"]["status"] == "FAILED"
    assert recovered.json()["task"]["error_code"] == error_code
    assert provider.submit_calls == 1
    assert count_rows(db_session, VideoRenderArtifact) == 0


@pytest.mark.parametrize(
    ("provider_error", "error_code"),
    [
        (
            ProviderConnectionError("sensitive network detail"),
            "submit_unknown_network",
        ),
        (
            ProviderTimeoutError("sensitive timeout detail"),
            "submit_unknown_timeout",
        ),
    ],
)
def test_uncertain_submit_blocks_all_automatic_resubmission(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    provider_error: Exception,
    error_code: str,
) -> None:
    project = create_video_project(db_session)
    provider = MockVisualProvider(submit_error=provider_error)
    install_contract_dependencies(tmp_path, provider)

    first = client.post(execute_path(project.id))
    recovered = client.get(latest_path(project.id))
    repeated = client.post(execute_path(project.id))

    assert first.status_code == 502
    assert recovered.status_code == 200
    assert repeated.status_code == 200
    body = repeated.json()
    assert body["task"]["status"] == "SUBMIT_UNKNOWN"
    assert body["task"]["error_code"] == error_code
    assert body["reused"] is True
    assert body["external_call"] is False
    assert provider.submit_calls == 1
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == 0
    assert "sensitive" not in recovered.text.casefold()


def test_refresh_progress_success_storage_and_recovery(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    provider = MockVisualProvider(
        snapshots=[
            VisualTaskSnapshot(
                provider_task_id="provider-task-001",
                status="RUNNING",
            ),
            VisualTaskSnapshot(
                provider_task_id="provider-task-001",
                status="SUCCEEDED",
                provider_output_url="https://provider.example/video.mp4",
            ),
        ]
    )
    fetcher = install_contract_dependencies(tmp_path, provider)
    executed = client.post(execute_path(project.id)).json()
    task_id = executed["task"]["id"]

    processing = client.post(
        f"/api/v1/video-render-tasks/{task_id}/refresh"
    )
    succeeded = client.post(
        f"/api/v1/video-render-tasks/{task_id}/refresh"
    )
    repeated = client.post(
        f"/api/v1/video-render-tasks/{task_id}/refresh"
    )
    recovered = client.get(latest_path(project.id))

    assert processing.status_code == 200
    assert processing.json()["task"]["status"] == "RUNNING"
    assert succeeded.status_code == 200
    assert succeeded.json()["task"]["status"] == "SUCCEEDED"
    assert repeated.status_code == 200
    assert repeated.json()["external_call"] is False
    assert recovered.status_code == 200
    body = recovered.json()
    assert body["recovered"] is True
    assert body["task"]["status"] == "SUCCEEDED"
    assert body["artifact"]["available"] is True
    assert body["artifact"]["content_type"] == "video/mp4"
    assert "storage_path" not in recovered.text
    assert "provider_output_url" not in recovered.text
    assert provider.submit_calls == 1
    assert provider.fetch_calls == 2
    assert fetcher.calls == 1
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == 1

    artifact_id = body["artifact"]["id"]
    metadata = client.get(f"/api/v1/video-render-artifacts/{artifact_id}")
    content = client.get(
        f"/api/v1/video-render-artifacts/{artifact_id}/content"
    )
    assert metadata.status_code == 200
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("video/mp4")
    assert content.content == b"safe-fake-mp4"
    assert "storage_path" not in metadata.text
    assert str(tmp_path.resolve()) not in metadata.text


def test_refresh_never_submits_and_rejects_created_task(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    task = VideoRenderService(db_session).create_render_task(
        project.id,
        VideoRenderTaskCreate(
            scene_sequence=1,
            resolution="720P",
            idempotency_key="created-not-submitted",
        ),
    )
    provider = MockVisualProvider()
    install_contract_dependencies(tmp_path, provider)

    response = client.post(
        f"/api/v1/video-render-tasks/{task.id}/refresh"
    )

    assert response.status_code == 409
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0


def test_failed_refresh_creates_no_artifact(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    provider = MockVisualProvider(
        snapshots=[
            VisualTaskSnapshot(
                provider_task_id="provider-task-001",
                status="FAILED",
                error_code="raw-provider-code",
                error_message="raw provider response",
            )
        ]
    )
    install_contract_dependencies(tmp_path, provider)
    task = client.post(execute_path(project.id)).json()["task"]

    response = client.post(
        f"/api/v1/video-render-tasks/{task['id']}/refresh"
    )

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "FAILED"
    assert response.json()["task"]["error_code"] == "provider_failed"
    assert "raw-provider" not in response.text
    assert count_rows(db_session, VideoRenderArtifact) == 0


class FailingStorage(VideoArtifactStorage):
    def store(
        self,
        *,
        task_id: int,
        content: bytes,
        content_type: str,
    ):
        raise VideoArtifactError(
            "artifact_persist_failed",
            "Video artifact storage failed",
        )

    def resolve(self, relative_path: str):
        raise AssertionError("failed storage cannot resolve")

    def delete(self, relative_path: str) -> None:
        raise AssertionError("failed storage has no file to delete")


def test_storage_failure_is_not_reported_as_success(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    provider = MockVisualProvider(
        snapshots=[
            VisualTaskSnapshot(
                provider_task_id="provider-task-001",
                status="SUCCEEDED",
                provider_output_url="https://provider.example/video.mp4",
            )
        ]
    )
    install_contract_dependencies(
        tmp_path,
        provider,
        storage=FailingStorage(),
    )
    task = client.post(execute_path(project.id)).json()["task"]

    response = client.post(
        f"/api/v1/video-render-tasks/{task['id']}/refresh"
    )
    recovered = client.get(latest_path(project.id))

    assert response.status_code == 502
    assert recovered.status_code == 200
    assert recovered.json()["task"]["status"] == "ARTIFACT_PERSIST_FAILED"
    assert recovered.json()["artifact"] is None
    assert count_rows(db_session, VideoRenderArtifact) == 0


def test_latest_task_is_isolated_by_exact_video_project(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    first = create_video_project(db_session)
    second = create_video_project(db_session)
    provider = MockVisualProvider()
    install_contract_dependencies(tmp_path, provider)

    first_task = client.post(execute_path(first.id)).json()["task"]
    second_task = client.post(execute_path(second.id)).json()["task"]

    first_latest = client.get(latest_path(first.id))
    second_latest = client.get(latest_path(second.id))

    assert first_latest.json()["task"]["id"] == first_task["id"]
    assert second_latest.json()["task"]["id"] == second_task["id"]
    assert first_latest.json()["video_project_id"] == first.id
    assert second_latest.json()["video_project_id"] == second.id


def test_local_storage_rejects_path_traversal_type_and_size(
    tmp_path: Path,
) -> None:
    storage = LocalVideoArtifactStorage(tmp_path.resolve(), 4)

    with pytest.raises(VideoArtifactError):
        storage.resolve("../outside.mp4")
    with pytest.raises(VideoArtifactError):
        storage.store(
            task_id=1,
            content=b"abc",
            content_type="text/plain",
        )
    with pytest.raises(VideoArtifactError):
        storage.store(
            task_id=1,
            content=b"12345",
            content_type="video/mp4",
        )
    assert list(tmp_path.iterdir()) == []


def test_artifact_content_api_cannot_read_outside_storage_root(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    project = create_video_project(db_session)
    service = VideoRenderService(db_session)
    task = service.create_render_task(
        project.id,
        VideoRenderTaskCreate(
            scene_sequence=1,
            resolution="720P",
            idempotency_key="unsafe-artifact-path-test",
        ),
    )
    service.transition_status(task.id, "SUBMITTED")
    service.transition_status(task.id, "SUCCEEDED")
    artifact = service.save_artifact(
        task.id,
        VideoRenderArtifactCreate(
            storage_path="../outside.mp4",
            metadata={
                "content_type": "video/mp4",
                "size_bytes": 4,
            },
        ),
    )
    provider = MockVisualProvider()
    install_contract_dependencies(tmp_path, provider)

    response = client.get(
        f"/api/v1/video-render-artifacts/{artifact.id}/content"
    )

    assert response.status_code == 404
    assert str(tmp_path.parent.resolve()) not in response.text
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0
