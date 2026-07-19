from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.video_renders import (
    get_live_visual_provider_factory,
)
from app.core.config import settings
from app.main import app
from app.models import VideoRenderTask
from app.providers.base import ProviderConnectionError
from app.services.video_render_service import VideoRenderService
from tests.test_video_render_artifact import (
    artifact_data,
    create_succeeded_render_task,
)
from tests.test_video_render_execution_service import MockVisualProvider
from tests.test_video_render_service import create_video_project


def live_path(video_project_id: int) -> str:
    return f"/api/v1/video-projects/{video_project_id}/live-render"


def enable_live_demo(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_live_wanx_demo", True)


def override_provider(provider: MockVisualProvider) -> None:
    app.dependency_overrides[get_live_visual_provider_factory] = (
        lambda: lambda: provider
    )


def clear_provider_override() -> None:
    app.dependency_overrides.pop(get_live_visual_provider_factory, None)


def test_live_render_rejects_when_feature_is_disabled(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "enable_live_wanx_demo", False)
    project = create_video_project(db_session)

    response = client.post(
        live_path(project.id), json={"confirm_live_generation": True}
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Live Wanx demo is disabled"
    assert db_session.scalar(select(func.count()).select_from(VideoRenderTask)) == 0


def test_live_render_requires_literal_confirmation(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    enable_live_demo(monkeypatch)
    project = create_video_project(db_session)

    response = client.post(
        live_path(project.id), json={"confirm_live_generation": False}
    )

    assert response.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(VideoRenderTask)) == 0


def test_first_live_render_submits_provider_once(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    enable_live_demo(monkeypatch)
    project = create_video_project(db_session)
    provider = MockVisualProvider()
    override_provider(provider)
    try:
        response = client.post(
            live_path(project.id), json={"confirm_live_generation": True}
        )
    finally:
        clear_provider_override()

    assert response.status_code == 200
    assert response.json()["external_call"] is True
    assert response.json()["task"]["status"] == "PENDING"
    assert response.json()["task"]["scene_sequence"] == 1
    assert response.json()["task"]["duration_seconds"] == 4
    assert response.json()["task"]["resolution"] == "720P"
    assert response.json()["task"]["idempotency_key"] == (
        f"live-presentation:{project.id}:scene-1:720p:v1"
    )
    assert provider.submit_calls == 1


def test_repeated_live_render_does_not_create_or_submit_again(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    enable_live_demo(monkeypatch)
    project = create_video_project(db_session)
    provider = MockVisualProvider()
    override_provider(provider)
    try:
        first = client.post(
            live_path(project.id), json={"confirm_live_generation": True}
        )
        second = client.post(
            live_path(project.id), json={"confirm_live_generation": True}
        )
    finally:
        clear_provider_override()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    assert second.json()["external_call"] is False
    assert provider.submit_calls == 1
    assert db_session.scalar(select(func.count()).select_from(VideoRenderTask)) == 1


def test_existing_succeeded_artifact_returns_without_provider(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    enable_live_demo(monkeypatch)
    task = create_succeeded_render_task(db_session)
    artifact = VideoRenderService(db_session).save_artifact(
        task.id, artifact_data()
    )

    def forbidden_factory():
        raise AssertionError("Existing artifact resolved a provider")

    app.dependency_overrides[get_live_visual_provider_factory] = (
        lambda: forbidden_factory
    )
    try:
        response = client.post(
            live_path(task.video_project_id),
            json={"confirm_live_generation": True},
        )
    finally:
        clear_provider_override()

    assert response.status_code == 200
    assert response.json()["external_call"] is False
    assert response.json()["task"]["id"] == task.id
    assert response.json()["artifact"]["id"] == artifact.id


def test_live_render_maps_provider_failure_safely(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    enable_live_demo(monkeypatch)
    project = create_video_project(db_session)
    provider = MockVisualProvider(
        submit_error=ProviderConnectionError("sensitive upstream detail")
    )
    override_provider(provider)
    try:
        response = client.post(
            live_path(project.id), json={"confirm_live_generation": True}
        )
    finally:
        clear_provider_override()

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Visual generation provider request failed"
    )
    task = db_session.scalar(select(VideoRenderTask))
    assert task is not None
    assert task.status == "FAILED"
    assert task.error_code == "PROVIDER_SUBMIT_ERROR"
    assert "sensitive" not in (task.error_message or "")
    assert provider.submit_calls == 1
