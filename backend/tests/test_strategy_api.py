import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.main import app
from app.models import (
    CopyMatrix,
    MarketingStrategy,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.providers.base import TextGenerationProvider
from app.repositories.strategy import MarketingStrategyRepository
from app.schemas.strategy import MarketingStrategySchema


class FakeStrategyProvider(TextGenerationProvider):
    def generate(self, prompt: str) -> str:
        assert "Portable Blender" in prompt
        return json.dumps(
            {
                "positioning": "Everyday portable nutrition helper.",
                "audience_insights": ["Young professionals need speed."],
                "angles": ["Blend between meetings"],
                "risks": ["Do not promise medical outcomes."],
                "evidence": ["Portable design and USB charging."],
            }
        )


class InvalidWhitespaceStrategyProvider(TextGenerationProvider):
    def generate(self, prompt: str) -> str:
        assert "Portable Blender" in prompt
        return json.dumps(
            {
                "positioning": "SENSITIVE_PROVIDER_RAW_PAYLOAD",
                "audience_insights": ["Audience"],
                "angles": [" \t\n "],
                "risks": ["Risk"],
                "evidence": ["Evidence"],
            }
        )


def test_strategy_api_returns_structured_result(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    app.dependency_overrides[get_text_generation_provider] = FakeStrategyProvider
    try:
        product = client.post("/api/v1/products", json=product_payload).json()

        response = client.post(f"/api/v1/products/{product['id']}/strategy")

        assert response.status_code == 200
        data = response.json()
        assert data | {
            "id": data["id"],
            "product_id": data["product_id"],
            "created_at": data["created_at"],
        } == {
            "id": data["id"],
            "product_id": product["id"],
            "created_at": data["created_at"],
            "positioning": "Everyday portable nutrition helper.",
            "audience_insights": ["Young professionals need speed."],
            "angles": ["Blend between meetings"],
            "risks": ["Do not promise medical outcomes."],
            "evidence": ["Portable design and USB charging."],
        }
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)


def test_strategy_api_rejects_blank_provider_item_safely(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    app.dependency_overrides[
        get_text_generation_provider
    ] = InvalidWhitespaceStrategyProvider
    try:
        product = client.post("/api/v1/products", json=product_payload).json()

        response = client.post(f"/api/v1/products/{product['id']}/strategy")

        assert response.status_code == 502
        response_text = response.text
        assert response.json()["error"]["message"] == (
            "Qwen returned invalid strategy data"
        )
        assert "SENSITIVE_PROVIDER_RAW_PAYLOAD" not in response_text
        assert "Traceback" not in response_text
        for model in (
            MarketingStrategy,
            CopyMatrix,
            VideoProject,
            VideoRenderTask,
            VideoRenderArtifact,
        ):
            assert db_session.scalar(select(func.count(model.id))) == 0
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)


def add_strategy(
    db_session: Session, product_id: int, positioning: str
) -> MarketingStrategy:
    return MarketingStrategyRepository(db_session).create(
        product_id,
        MarketingStrategySchema(
            positioning=positioning,
            audience_insights=["Audience"],
            angles=["Angle"],
            risks=["Risk"],
            evidence=["Evidence"],
        ),
    )


def test_latest_strategy_requires_existing_product(client: TestClient) -> None:
    response = client.get("/api/v1/products/999/strategies/latest")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Product not found"


def test_latest_strategy_reports_empty_result(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()

    response = client.get(
        f"/api/v1/products/{product['id']}/strategies/latest"
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Marketing strategy not found"


def test_latest_strategy_is_product_scoped_and_read_only(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    first_product = client.post("/api/v1/products", json=product_payload).json()
    second_payload = {**product_payload, "name": "Second Product"}
    second_product = client.post("/api/v1/products", json=second_payload).json()
    add_strategy(db_session, first_product["id"], "Older positioning")
    latest = add_strategy(db_session, first_product["id"], "Latest positioning")
    add_strategy(db_session, second_product["id"], "Other product positioning")
    provider_calls = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("Latest strategy read must not resolve a Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    counts_before = {
        model: db_session.scalar(select(func.count(model.id)))
        for model in (
            MarketingStrategy,
            CopyMatrix,
            VideoProject,
            VideoRenderTask,
            VideoRenderArtifact,
        )
    }

    response = client.get(
        f"/api/v1/products/{first_product['id']}/strategies/latest"
    )

    assert response.status_code == 200
    assert response.json()["id"] == latest.id
    assert response.json()["product_id"] == first_product["id"]
    assert response.json()["positioning"] == "Latest positioning"
    assert provider_calls == 0
    for model, count in counts_before.items():
        assert db_session.scalar(select(func.count(model.id))) == count
