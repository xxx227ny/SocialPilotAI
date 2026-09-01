from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    get_provider_output_fetcher,
    get_video_artifact_storage,
    get_visual_generation_provider,
)
from app.api.v1.routes import video_renders
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import (
    ExecutionWorker,
    WorkerRunResult,
    WorkerRunStatus,
)
from app.main import app
from app.models import ExecutionJob, VideoRenderArtifact, VideoRenderTask
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
from app.services.video_render_operation_service import (
    VideoProjectRenderExecutionService,
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
    app.dependency_overrides[get_provider_output_fetcher] = lambda: selected_fetcher
    app.dependency_overrides[get_video_artifact_storage] = lambda: selected_storage
    return selected_fetcher


def count_rows(db_session: Session, model: type) -> int:
    return int(db_session.scalar(select(func.count()).select_from(model)) or 0)


def execute_path(project_id: int) -> str:
    return f"/api/v1/video-projects/{project_id}/render-execution"


def latest_path(project_id: int) -> str:
    return f"/api/v1/video-projects/{project_id}/render-tasks/latest"


def enqueue_submit(
    client: TestClient,
    project_id: int,
    *,
    cost_confirmed: bool = True,
):
    preflight = client.get(f"/api/v1/video-projects/{project_id}/render-preflight")
    assert preflight.status_code == 200
    checked = preflight.json()
    payload = {
        "product_id": checked["product_id"],
        "marketing_strategy_id": checked["marketing_strategy_id"],
        "copy_matrix_id": checked["copy_matrix_id"],
        "input_digest": checked["input_digest"],
        "preflight_digest": checked["preflight_digest"],
        "preflight_expires_at": checked["expires_at"],
        "cost_confirmed": cost_confirmed,
    }
    return client.post(execute_path(project_id), json=payload)


def enqueue_refresh(
    client: TestClient,
    task_id: int,
    project_id: int,
    request_id: str,
):
    return client.post(
        f"/api/v1/video-render-tasks/{task_id}/refresh",
        json={
            "video_project_id": project_id,
            "refresh_request_id": request_id,
        },
    )


def run_fake_worker(
    db_session: Session,
    tmp_path: Path,
    provider: MockVisualProvider,
    *,
    fetcher: FakeOutputFetcher | None = None,
    storage: VideoArtifactStorage | None = None,
    worker_id: str = "video-contract-worker",
) -> WorkerRunResult:
    sessions = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=contract_settings(tmp_path),
        wanx_provider_factory=lambda _: provider,
        output_fetcher=fetcher or FakeOutputFetcher(),
        artifact_storage=storage
        or LocalVideoArtifactStorage(tmp_path.resolve(), 1_000_000),
    )
    return ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id=worker_id,
        heartbeat_interval_seconds=0.1,
    ).run_once()


def get_job(client: TestClient, job_id: int):
    response = client.get(f"/api/v1/execution-jobs/{job_id}")
    assert response.status_code == 200
    return response.json()


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

    unconfirmed = enqueue_submit(client, project.id, cost_confirmed=False)
    response = enqueue_submit(client, project.id)

    assert unconfirmed.status_code == 422
    assert response.status_code == 409
    assert provider_resolutions == 0
    assert count_rows(db_session, ExecutionJob) == 0
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

    first = enqueue_submit(client, project.id)
    repeated = enqueue_submit(client, project.id)

    assert first.status_code == 201
    assert repeated.status_code == 201
    first_body = first.json()
    repeated_body = repeated.json()
    assert first_body["job"]["source_id"] == project.id
    assert first_body["job"]["status"] == "QUEUED"
    assert first_body["reused"] is False
    assert repeated_body["job"]["id"] == first_body["job"]["id"]
    assert repeated_body["reused"] is True
    assert provider.submit_calls == 0
    assert count_rows(db_session, VideoRenderTask) == 0

    result = run_fake_worker(db_session, tmp_path, provider)
    assert result.status == WorkerRunStatus.SUCCEEDED
    job = get_job(client, first_body["job"]["id"])
    assert job["result_entity_type"] == "video_render_task"
    exact = client.get(f"/api/v1/video-render-tasks/{job['result_entity_id']}/recovery")
    assert exact.status_code == 200
    assert exact.json()["video_project_id"] == project.id
    assert exact.json()["task"]["id"] == job["result_entity_id"]
    assert exact.json()["task"]["status"] == "PENDING"
    assert provider.submit_calls == 1
    assert count_rows(db_session, VideoRenderTask) == 1
    serialized = (first.text + exact.text).casefold()
    assert "render_prompt" not in serialized
    assert "idempotency_key" not in exact.text.casefold()
    assert "workspace-render" not in first.text.casefold()
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

    response = enqueue_submit(client, project.id)

    assert response.status_code == 409
    assert provider.submit_calls == 0
    assert count_rows(db_session, ExecutionJob) == 0
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

    service = VideoProjectRenderExecutionService(
        db_session,
        provider,
        contract_settings(tmp_path),
        FakeOutputFetcher(),
        LocalVideoArtifactStorage(tmp_path.resolve(), 1_000_000),
    )
    with pytest.raises(AppError) as raised:
        asyncio.run(service.execute(project.id))
    recovered = client.get(latest_path(project.id))

    assert raised.value.status_code == status_code
    assert "secret" not in str(raised.value)
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

    first = enqueue_submit(client, project.id)
    assert first.status_code == 201
    result = run_fake_worker(
        db_session,
        tmp_path,
        provider,
        worker_id=f"uncertain-{error_code}-worker",
    )
    recovered = client.get(latest_path(project.id))
    repeated = enqueue_submit(client, project.id)
    retry = client.post(
        f"/api/v1/execution-jobs/{first.json()['job']['id']}/retry",
        json={"retry_confirmed": True},
    )

    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert recovered.status_code == 200
    assert repeated.status_code == 201
    assert retry.status_code == 409
    body = recovered.json()
    assert body["task"]["status"] == "SUBMIT_UNKNOWN"
    assert body["task"]["error_code"] == error_code
    assert repeated.json()["reused"] is True
    assert repeated.json()["job"]["status"] == "SUBMIT_UNKNOWN"
    assert provider.submit_calls == 1
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == 0
    assert "sensitive" not in recovered.text.casefold()


def test_refresh_progress_success_storage_and_recovery(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
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
    submitted = enqueue_submit(client, project.id)
    assert submitted.status_code == 201
    assert (
        run_fake_worker(
            db_session,
            tmp_path,
            provider,
            fetcher=fetcher,
            worker_id="progress-submit-worker",
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    submit_job = get_job(client, submitted.json()["job"]["id"])
    task_id = submit_job["result_entity_id"]

    processing = enqueue_refresh(client, task_id, project.id, "refresh-progress-0001")
    assert processing.status_code == 201
    assert (
        run_fake_worker(
            db_session,
            tmp_path,
            provider,
            fetcher=fetcher,
            worker_id="progress-refresh-worker-1",
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    processing_exact = client.get(f"/api/v1/video-render-tasks/{task_id}/recovery")
    succeeded = enqueue_refresh(client, task_id, project.id, "refresh-success-0002")
    assert succeeded.status_code == 201
    assert (
        run_fake_worker(
            db_session,
            tmp_path,
            provider,
            fetcher=fetcher,
            worker_id="progress-refresh-worker-2",
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    repeated = enqueue_refresh(client, task_id, project.id, "refresh-success-0002")
    recovered = client.get(latest_path(project.id))

    assert processing_exact.json()["task"]["status"] == "RUNNING"
    assert (
        get_job(client, succeeded.json()["job"]["id"])["result_entity_type"]
        == "video_render_artifact"
    )
    assert repeated.status_code == 201
    assert repeated.json()["reused"] is True
    assert recovered.status_code == 200
    body = recovered.json()
    assert body["recovered"] is True
    assert body["task"]["status"] == "SUCCEEDED"
    assert body["artifact"]["video_render_task_id"] == body["task"]["id"]
    assert "content_url" not in body["artifact"]
    assert "storage_path" not in recovered.text
    assert "provider_output_url" not in recovered.text
    assert provider.submit_calls == 1
    assert provider.fetch_calls == 2
    assert fetcher.calls == 1
    assert count_rows(db_session, VideoRenderTask) == 1
    assert count_rows(db_session, VideoRenderArtifact) == 1

    artifact_id = body["artifact"]["id"]
    metadata = client.get(f"/api/v1/video-render-artifacts/{artifact_id}")
    content = client.get(f"/api/v1/video-render-artifacts/{artifact_id}/content")
    preview_path = tmp_path / "judge-preview.mp4"
    preview_path.write_bytes(b"preview-mp4")
    monkeypatch.setattr(
        video_renders,
        "video_preview_path",
        lambda source, digest, ffmpeg: preview_path,
    )
    preview = client.get(
        f"/api/v1/video-render-artifacts/{artifact_id}/preview",
        headers={"Range": "bytes=0-3"},
    )
    assert metadata.status_code == 200
    assert metadata.json()["content_available"] is True
    assert metadata.json()["content_type"] == "video/mp4"
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("video/mp4")
    assert content.headers["cache-control"] == "private, max-age=86400, immutable"
    assert content.headers["cdn-cache-control"] == "no-store"
    assert content.content == b"safe-fake-mp4"
    assert preview.status_code == 206
    assert preview.content == b"prev"
    assert preview.headers["content-range"] == "bytes 0-3/11"
    assert preview.headers["cache-control"] == "private, max-age=86400, immutable"
    assert preview.headers["vary"] == "Cookie"
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

    response = enqueue_refresh(client, task.id, project.id, "created-refresh-0001")

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
    submitted = enqueue_submit(client, project.id)
    assert (
        run_fake_worker(
            db_session, tmp_path, provider, worker_id="failed-submit-worker"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    task_id = get_job(client, submitted.json()["job"]["id"])["result_entity_id"]
    response = enqueue_refresh(client, task_id, project.id, "failed-refresh-0001")
    assert response.status_code == 201
    assert (
        run_fake_worker(
            db_session, tmp_path, provider, worker_id="failed-refresh-worker"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    exact = client.get(f"/api/v1/video-render-tasks/{task_id}/recovery")

    assert exact.json()["task"]["status"] == "FAILED"
    assert exact.json()["task"]["error_code"] == "provider_failed"
    assert "raw-provider" not in exact.text
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
    submitted = enqueue_submit(client, project.id)
    assert (
        run_fake_worker(
            db_session,
            tmp_path,
            provider,
            storage=FailingStorage(),
            worker_id="storage-submit-worker",
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    task_id = get_job(client, submitted.json()["job"]["id"])["result_entity_id"]
    response = enqueue_refresh(client, task_id, project.id, "storage-refresh-0001")
    assert response.status_code == 201
    worker_result = run_fake_worker(
        db_session,
        tmp_path,
        provider,
        storage=FailingStorage(),
        worker_id="storage-refresh-worker",
    )
    recovered = client.get(latest_path(project.id))

    assert worker_result.status == WorkerRunStatus.FAILED
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

    first_submit = enqueue_submit(client, first.id)
    assert (
        run_fake_worker(
            db_session, tmp_path, provider, worker_id="isolation-worker-1"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    first_task_id = get_job(client, first_submit.json()["job"]["id"])[
        "result_entity_id"
    ]
    second_submit = enqueue_submit(client, second.id)
    assert (
        run_fake_worker(
            db_session, tmp_path, provider, worker_id="isolation-worker-2"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    second_task_id = get_job(client, second_submit.json()["job"]["id"])[
        "result_entity_id"
    ]

    first_latest = client.get(latest_path(first.id))
    second_latest = client.get(latest_path(second.id))

    assert first_latest.json()["task"]["id"] == first_task_id
    assert second_latest.json()["task"]["id"] == second_task_id
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

    response = client.get(f"/api/v1/video-render-artifacts/{artifact.id}/content")

    assert response.status_code == 404
    assert str(tmp_path.parent.resolve()) not in response.text
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0
