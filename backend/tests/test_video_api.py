import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.main import app
from app.models import MarketingStrategy
from app.providers.base import TextGenerationProvider
from tests.test_content_studio_service import add_video_sources, valid_plan


class FakeVideoApiProvider(TextGenerationProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        assert "structured short-video production plan" in prompt
        return json.dumps(valid_plan())


def test_video_api_returns_valid_plan_with_source_ids(
    client: TestClient, db_session: Session
) -> None:
    product, strategy, copy_matrix = add_video_sources(db_session)
    provider = FakeVideoApiProvider()
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{product.id}/video-projects",
            json={
                "platform": "TikTok",
                "duration_seconds": 30,
                "aspect_ratio": "9:16",
            },
        )
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == product.id
    assert body["marketing_strategy_id"] == strategy.id
    assert body["copy_matrix_id"] == copy_matrix.id
    assert sum(scene["duration_seconds"] for scene in body["scenes"]) == 30
    assert body["status"] == "planned"
    assert "video_url" not in body
    assert "audio" not in body
    assert "subtitles" not in body
    assert "provider_task_id" not in body
    assert provider.calls == 1


def test_video_api_requires_copy_matrix(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = client.post("/api/v1/products", json=product_payload).json()["id"]
    db_session.add(
        MarketingStrategy(
            product_id=product_id,
            positioning="Portable daily nutrition.",
            audience_insights=["Busy professionals value convenience."],
            angles=["Blend anywhere"],
            risks=["Avoid health guarantees."],
            evidence=["USB rechargeable."],
        )
    )
    db_session.commit()
    provider = FakeVideoApiProvider()
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{product_id}/video-projects",
            json={},
        )
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 409
    assert provider.calls == 0
