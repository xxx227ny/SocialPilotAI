from fastapi.testclient import TestClient

from app.api.dependencies import get_text_generation_provider
from app.core.config import settings
from app.main import app
from app.providers.base import TextGenerationProvider


class ForbiddenDemoProvider(TextGenerationProvider):
    def generate(self, prompt: str) -> str:
        raise AssertionError(f"Demo must not call a provider: {prompt}")


def test_dashboard_handles_missing_workflow_data(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_id = client.post("/api/v1/products", json=product_payload).json()["id"]

    response = client.get(f"/api/v1/dashboard/products/{product_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["data_source"] == "stored_records"
    assert body["demo"] is None
    assert body["strategy"] is None
    assert body["copy_matrix"] is None
    assert body["video_project"] is None
    assert body["growth"] == {
        "status": "missing",
        "metrics": None,
        "platform_metrics": [],
        "recommendation": None,
    }
    assert [step["status"] for step in body["pipeline"]] == [
        "complete",
        "missing",
        "missing",
        "missing",
        "missing",
    ]


def test_demo_api_returns_complete_snapshot_without_provider_dependency(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "app_environment", "development")
    app.dependency_overrides[get_text_generation_provider] = ForbiddenDemoProvider
    try:
        response = client.post("/api/v1/demo/prepare")
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 200
    body = response.json()
    assert body["data_source"] == "demo_snapshot"
    assert body["demo"] == {
        "slug": "portable-blender-growth-loop",
        "label": "Portable Blender Growth Loop",
        "source": "preset_fixture",
        "fixture_version": 1,
        "badge": "Demo Snapshot",
        "ai_calls": 0,
        "notice": "使用预置演示数据",
    }
    assert all(step["status"] == "complete" for step in body["pipeline"])
    assert body["strategy"] is not None
    assert [copy["platform"] for copy in body["copy_matrix"]["copies"]] == [
        "TikTok",
        "Instagram",
        "Facebook",
        "Pinterest",
    ]
    assert body["video_project"]["status"] == "planned"
    assert body["growth"]["recommendation"] is not None
