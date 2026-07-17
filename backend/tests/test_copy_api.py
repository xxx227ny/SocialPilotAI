import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.main import app
from app.models import MarketingStrategy
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
