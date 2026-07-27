from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_visual_generation_provider
from app.core.config import Settings, get_settings
from app.main import app
from app.providers.visual_base import VisualTaskSnapshot
from tests.test_video_render_execution_service import MockVisualProvider
from tests.test_video_render_service import create_video_project


def enabled_render_settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_video_render_execution=True,
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
    client: TestClient, db_session: Session
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
    app.dependency_overrides[get_settings] = enabled_render_settings
    app.dependency_overrides[get_visual_generation_provider] = lambda: provider
    task = create_task_through_api(client, db_session)

    submitted = client.post(
        f"/api/v1/video-render-tasks/{task['id']}/submit"
    )
    refreshed = client.post(
        f"/api/v1/video-render-tasks/{task['id']}/refresh"
    )
    repeated = client.post(
        f"/api/v1/video-render-tasks/{task['id']}/refresh"
    )

    assert submitted.status_code == 200
    assert submitted.json()["external_call"] is True
    assert submitted.json()["task"]["status"] == "PENDING"
    assert refreshed.status_code == 200
    assert refreshed.json()["task"]["status"] == "SUCCEEDED"
    assert refreshed.json()["artifact"]["provider_output_url"] == (
        "https://provider.example/video.mp4"
    )
    assert repeated.status_code == 200
    assert repeated.json()["external_call"] is False
    assert provider.submit_calls == 1
    assert provider.fetch_calls == 1


def test_execution_api_rejects_duplicate_submit(
    client: TestClient, db_session: Session
) -> None:
    provider = MockVisualProvider()
    app.dependency_overrides[get_settings] = enabled_render_settings
    app.dependency_overrides[get_visual_generation_provider] = lambda: provider
    task = create_task_through_api(client, db_session)

    first = client.post(f"/api/v1/video-render-tasks/{task['id']}/submit")
    duplicate = client.post(
        f"/api/v1/video-render-tasks/{task['id']}/submit"
    )

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert provider.submit_calls == 1


def test_execution_api_gate_stops_before_provider_resolution(
    client: TestClient,
    db_session: Session,
) -> None:
    task = create_task_through_api(client, db_session)
    provider_resolutions = 0

    def forbidden_provider():
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("disabled execution resolved a Provider")

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_visual_generation_provider] = forbidden_provider

    response = client.post(
        f"/api/v1/video-render-tasks/{task['id']}/submit"
    )

    assert response.status_code == 503
    assert provider_resolutions == 0
    assert task["status"] == "CREATED"
