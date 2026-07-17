import json

from fastapi.testclient import TestClient

from app.api.dependencies import get_text_generation_provider
from app.main import app
from app.providers.base import TextGenerationProvider


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


def test_strategy_api_returns_structured_result(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    app.dependency_overrides[get_text_generation_provider] = FakeStrategyProvider
    try:
        product = client.post("/api/v1/products", json=product_payload).json()

        response = client.post(f"/api/v1/products/{product['id']}/strategy")

        assert response.status_code == 200
        assert response.json() == {
            "positioning": "Everyday portable nutrition helper.",
            "audience_insights": ["Young professionals need speed."],
            "angles": ["Blend between meetings"],
            "risks": ["Do not promise medical outcomes."],
            "evidence": ["Portable design and USB charging."],
        }
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)
