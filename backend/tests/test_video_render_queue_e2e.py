from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.main import app
from app.models import ExecutionJob, VideoRenderTask
from app.providers.base import ProviderConnectionError
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from tests.test_video_render_execution_service import (
    FakeOutputFetcher,
    MockVisualProvider,
)
from tests.test_video_render_service import create_video_project


def settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        enable_video_render_execution=True,
        wanx_api_key="fake-queue-key",
        wanx_workspace_id="fake-workspace",
        wanx_region="cn-beijing",
        video_artifact_storage_root=str(root.resolve()),
        video_artifact_max_bytes=1_000_000,
    )


def enqueue(client: TestClient, project_id: int) -> int:
    checked = client.get(
        f"/api/v1/video-projects/{project_id}/render-preflight"
    ).json()
    response = client.post(
        f"/api/v1/video-projects/{project_id}/render-execution",
        json={
            "product_id": checked["product_id"],
            "marketing_strategy_id": checked["marketing_strategy_id"],
            "copy_matrix_id": checked["copy_matrix_id"],
            "input_digest": checked["input_digest"],
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
            "cost_confirmed": True,
        },
    )
    assert response.status_code == 201
    return response.json()["job"]["id"]


def worker(
    db_session: Session,
    tmp_path: Path,
    provider: MockVisualProvider,
    worker_id: str,
) -> ExecutionWorker:
    sessions = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    app_settings = settings(tmp_path)
    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=app_settings,
        wanx_provider_factory=lambda _: provider,
        output_fetcher=FakeOutputFetcher(),
        artifact_storage=LocalVideoArtifactStorage(tmp_path.resolve(), 1_000_000),
    )
    return ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id=worker_id,
        heartbeat_interval_seconds=0.1,
    )


def test_fake_queue_submit_is_once_across_repeated_http_and_two_workers(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    project = create_video_project(db_session)
    app.dependency_overrides[get_settings] = lambda: settings(tmp_path)
    first_job_id = enqueue(client, project.id)
    assert enqueue(client, project.id) == first_job_id
    provider = MockVisualProvider()
    first = worker(db_session, tmp_path, provider, "wanx-e2e-worker-1")
    second = worker(db_session, tmp_path, provider, "wanx-e2e-worker-2")

    assert first.run_once().status == WorkerRunStatus.SUCCEEDED
    assert second.run_once().status == WorkerRunStatus.NO_JOB
    assert enqueue(client, project.id) == first_job_id
    db_session.expire_all()
    job = db_session.get(ExecutionJob, first_job_id)
    assert job is not None
    assert job.result_entity_type == "video_render_task"
    assert db_session.get(VideoRenderTask, job.result_entity_id) is not None
    assert provider.submit_calls == 1
    assert provider.fetch_calls == 0


def test_submit_unknown_never_retries_or_resubmits(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    project = create_video_project(db_session)
    app.dependency_overrides[get_settings] = lambda: settings(tmp_path)
    job_id = enqueue(client, project.id)
    provider = MockVisualProvider(
        submit_error=ProviderConnectionError("fake uncertain transport")
    )
    execution_worker = worker(
        db_session, tmp_path, provider, "wanx-unknown-worker"
    )

    assert execution_worker.run_once().status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert execution_worker.run_once().status == WorkerRunStatus.NO_JOB
    retry = client.post(
        f"/api/v1/execution-jobs/{job_id}/retry",
        json={"retry_confirmed": True},
    )
    assert retry.status_code == 409
    assert provider.submit_calls == 1
    assert provider.fetch_calls == 0
