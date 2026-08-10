from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_visual_generation_provider
from app.core.config import Settings, get_settings
from app.execution.worker import WorkerRunStatus
from app.main import app
from app.models import ExecutionJob, VideoRenderTask
from app.providers.visual_base import VisualTaskSnapshot
from tests.test_video_render_contract import (
    enqueue_refresh,
    enqueue_submit,
    get_job,
    run_fake_worker,
)
from tests.test_video_render_execution_service import (
    FakeOutputFetcher,
    MockVisualProvider,
)
from tests.test_video_render_service import create_video_project


def enabled_render_settings(artifact_root: Path | None = None) -> Settings:
    return Settings(
        _env_file=None,
        enable_video_render_execution=True,
        wanx_api_key="safe-test-placeholder",
        wanx_workspace_id="safe-test-workspace",
        wanx_region="cn-beijing",
        video_artifact_storage_root=(
            str(artifact_root) if artifact_root is not None else None
        ),
    )


def create_task_through_api(
    client: TestClient, db_session: Session
) -> dict[str, object]:
    project = create_video_project(db_session)
    response = client.post(
        f"/api/v1/video-projects/{project.id}/render-tasks",
        json={
            "scene_sequence": 1,
            "resolution": "720P",
            "idempotency_key": "execution-api-task",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_execution_api_submits_and_refreshes_with_injected_provider(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = MockVisualProvider(
        snapshots=[
            VisualTaskSnapshot(
                provider_task_id="provider-task-001",
                status="SUCCEEDED",
                provider_output_url="https://provider.example/video.mp4",
                metadata={"usage": {"duration": 4}},
            )
        ]
    )
    fetcher = FakeOutputFetcher()
    app.dependency_overrides[get_settings] = lambda: enabled_render_settings(
        tmp_path
    )
    app.dependency_overrides[get_visual_generation_provider] = lambda: provider
    project = create_video_project(db_session)

    submitted = enqueue_submit(client, project.id)
    assert submitted.status_code == 201
    assert provider.submit_calls == 0
    assert run_fake_worker(
        db_session,
        tmp_path,
        provider,
        fetcher=fetcher,
        worker_id="execution-api-submit-worker",
    ).status == WorkerRunStatus.SUCCEEDED
    task_id = get_job(client, submitted.json()["job"]["id"])[
        "result_entity_id"
    ]
    refreshed = enqueue_refresh(
        client, task_id, project.id, "execution-api-refresh-0001"
    )
    assert refreshed.status_code == 201
    assert run_fake_worker(
        db_session,
        tmp_path,
        provider,
        fetcher=fetcher,
        worker_id="execution-api-refresh-worker",
    ).status == WorkerRunStatus.SUCCEEDED
    refresh_job = get_job(client, refreshed.json()["job"]["id"])
    repeated = enqueue_refresh(
        client, task_id, project.id, "execution-api-refresh-0001"
    )

    assert refresh_job["result_entity_type"] == "video_render_artifact"
    assert repeated.status_code == 201
    assert repeated.json()["reused"] is True
    assert provider.submit_calls == 1
    assert provider.fetch_calls == 1
    assert fetcher.calls == 1


def test_execution_api_rejects_duplicate_submit(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = MockVisualProvider()
    app.dependency_overrides[get_settings] = lambda: enabled_render_settings(
        tmp_path
    )
    app.dependency_overrides[get_visual_generation_provider] = lambda: provider
    project = create_video_project(db_session)

    first = enqueue_submit(client, project.id)
    duplicate = enqueue_submit(client, project.id)

    assert first.status_code == 201
    assert duplicate.status_code == 201
    assert duplicate.json()["reused"] is True
    assert duplicate.json()["job"]["id"] == first.json()["job"]["id"]
    assert run_fake_worker(
        db_session,
        tmp_path,
        provider,
        worker_id="execution-api-once-worker",
    ).status == WorkerRunStatus.SUCCEEDED
    assert provider.submit_calls == 1
    assert db_session.query(ExecutionJob).count() == 1
    assert db_session.query(VideoRenderTask).count() == 1


def test_execution_api_gate_stops_before_provider_resolution(
    client: TestClient,
    db_session: Session,
) -> None:
    project = create_video_project(db_session)
    provider_resolutions = 0

    def forbidden_provider():
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("disabled execution resolved a Provider")

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_visual_generation_provider] = forbidden_provider

    response = enqueue_submit(client, project.id)

    assert response.status_code == 409
    assert provider_resolutions == 0
    assert db_session.query(ExecutionJob).count() == 0
    assert db_session.query(VideoRenderTask).count() == 0


@pytest.mark.parametrize(
    "job_type",
    [
        "wanx.video_render.submit.v1",
        "wanx.video_render.refresh.v1",
    ],
)
def test_generic_execution_job_api_cannot_bypass_render_confirmation(
    client: TestClient,
    db_session: Session,
    job_type: str,
) -> None:
    response = client.post(
        "/api/v1/execution-jobs",
        json={
            "job_type": job_type,
            "source_type": "video_project",
            "source_id": 1,
            "input_digest": "a" * 64,
            "idempotency_key": f"unsafe-{job_type}",
            "input_payload": {},
            "cost_confirmed": True,
        },
    )

    assert response.status_code == 409
    assert "input_payload" not in response.text
    assert db_session.query(ExecutionJob).count() == 0
    assert db_session.query(VideoRenderTask).count() == 0
