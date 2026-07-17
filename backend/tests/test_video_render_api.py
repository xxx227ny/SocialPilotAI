from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.main import app
from app.providers.base import TextGenerationProvider
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
