from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_text_generation_provider,
    get_visual_generation_provider,
)
from app.main import app
from app.providers.base import TextGenerationProvider
from app.services.video_render_service import VideoRenderService
from tests.test_video_render_artifact import (
    artifact_data,
    create_succeeded_render_task,
)
from tests.test_video_render_service import create_video_project


class ForbiddenTextProvider(TextGenerationProvider):
    def generate(self, prompt: str) -> str:
        raise AssertionError(f"Render task creation called a provider: {prompt}")


def test_render_task_api_creates_and_reads_local_task_without_provider(
    client: TestClient, db_session: Session
) -> None:
    project = create_video_project(db_session)
    app.dependency_overrides[get_text_generation_provider] = ForbiddenTextProvider
    try:
        created = client.post(
            f"/api/v1/video-projects/{project.id}/render-tasks",
            json={
                "scene_sequence": 1,
                "resolution": "720P",
                "idempotency_key": "api-render-001",
            },
        )
        fetched = client.get(
            f"/api/v1/video-render-tasks/{created.json()['id']}"
        )
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert created.status_code == 201
    assert fetched.status_code == 200
    assert created.json() == fetched.json()
    assert created.json()["status"] == "CREATED"
    assert created.json()["external_call"] is False
    assert created.json()["provider_name"] is None
    assert created.json()["provider_task_id"] is None


def test_render_task_api_is_idempotent(
    client: TestClient, db_session: Session
) -> None:
    project = create_video_project(db_session)
    payload = {
        "scene_sequence": 2,
        "resolution": "720P",
        "idempotency_key": "api-render-repeat",
    }

    first = client.post(
        f"/api/v1/video-projects/{project.id}/render-tasks", json=payload
    )
    second = client.post(
        f"/api/v1/video-projects/{project.id}/render-tasks", json=payload
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_list_video_render_artifacts_returns_succeeded_artifact(
    client: TestClient, db_session: Session
) -> None:
    task = create_succeeded_render_task(db_session)
    artifact = VideoRenderService(db_session).save_artifact(
        task.id, artifact_data()
    )

    response = client.get(
        f"/api/v1/video-projects/{task.video_project_id}/render-artifacts"
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == artifact.id
    assert body[0]["video_render_task_id"] == task.id
    assert body[0]["provider_output_url"] == (
        "https://provider.example/result.mp4"
    )


def test_list_video_render_artifacts_returns_empty_list(
    client: TestClient, db_session: Session
) -> None:
    project = create_video_project(db_session)

    response = client.get(
        f"/api/v1/video-projects/{project.id}/render-artifacts"
    )

    assert response.status_code == 200
    assert response.json() == []


def test_list_video_render_artifacts_does_not_resolve_provider(
    client: TestClient, db_session: Session
) -> None:
    project = create_video_project(db_session)

    def forbidden_provider():
        raise AssertionError("Artifact read API resolved a visual provider")

    app.dependency_overrides[get_visual_generation_provider] = forbidden_provider
    try:
        response = client.get(
            f"/api/v1/video-projects/{project.id}/render-artifacts"
        )
    finally:
        app.dependency_overrides.pop(get_visual_generation_provider, None)

    assert response.status_code == 200
    assert response.json() == []
