import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.core.config import Settings, get_settings
from app.main import app
from app.models import CopyMatrix, MarketingStrategy
from app.providers.base import TextGenerationProvider


class FakeCopyProvider(TextGenerationProvider):
    def generate(self, prompt: str) -> str:
        assert "complete social media copy matrix" in prompt
        return json.dumps(
            {
                "copies": [
                    {
                        "platform": "TikTok",
                        "hook": "TikTok hook",
                        "caption": "Short UGC caption.",
                        "hashtags": ["#TikTokMadeMeBuyIt"],
                        "cta": "Watch the routine.",
                    },
                    {
                        "platform": "Instagram",
                        "hook": "Instagram hook",
                        "caption": "Lifestyle caption with visual mood.",
                        "hashtags": ["#Lifestyle"],
                        "cta": "Save this idea.",
                    },
                    {
                        "platform": "Facebook",
                        "hook": "Facebook hook",
                        "caption": "Functional value and purchase reasons.",
                        "hashtags": ["#ProductValue"],
                        "cta": "Learn more.",
                    },
                ]
            }
        )


def enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        dashscope_api_key="safe-test-placeholder",
        enable_copy_execution=True,
    )


def test_copy_api_returns_platform_matrix(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    db_session.add(
        MarketingStrategy(
            product_id=product["id"],
            positioning="Portable daily nutrition.",
            audience_insights=["Busy professionals need convenience."],
            angles=["Blend anywhere"],
            risks=["Avoid medical promises."],
            evidence=["Portable design."],
        )
    )
    db_session.commit()
    app.dependency_overrides[get_text_generation_provider] = FakeCopyProvider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        response = client.post(f"/api/v1/products/{product['id']}/copy")

        assert response.status_code == 200
        body = response.json()
        assert body["product_id"] == product["id"]
        assert [copy["platform"] for copy in body["copies"]] == [
            "TikTok",
            "Instagram",
            "Facebook",
        ]
        assert body["copies"][0]["hook"] == "TikTok hook"
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)
        app.dependency_overrides.pop(get_settings, None)


def test_copy_api_gate_stops_before_provider_resolution_and_write(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    db_session.add(
        MarketingStrategy(
            product_id=product["id"],
            positioning="Portable daily nutrition.",
            audience_insights=["Busy professionals need convenience."],
            angles=["Blend anywhere"],
            risks=["Avoid medical promises."],
            evidence=["Portable design."],
        )
    )
    db_session.commit()
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Disabled Copy execution must not resolve Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    try:
        response = client.post(f"/api/v1/products/{product['id']}/copy")

        assert response.status_code == 503
        assert response.json()["error"]["message"] == (
            "Copy execution is disabled by the server"
        )
        assert provider_resolutions == 0
        assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)
        app.dependency_overrides.pop(get_settings, None)
