import json
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.main import app
from app.models import AdCampaign, MarketingStrategy
from app.providers.base import TextGenerationProvider


class FakeGrowthProvider(TextGenerationProvider):
    calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        assert '"calculated_metrics"' in prompt
        assert '"impressions": 1000' in prompt
        assert '"ctr": 0.05' in prompt
        assert "campaign_name" not in prompt
        return json.dumps(
            {
                "problems": ["CTR trails the campaign target."],
                "recommendations": ["Test a stronger first-frame hook."],
                "budget_suggestion": "Keep total budget stable during the test.",
                "creative_suggestions": ["Show the portable use case earlier."],
            }
        )


def test_growth_api_returns_aggregate_metrics_and_mock_analysis(
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
    db_session.add_all(
        [
            AdCampaign(
                product_id=product_id,
                platform="TikTok",
                campaign_name="Awareness",
                date=date(2026, 7, 1),
                impressions=100,
                clicks=10,
                conversions=1,
                spend=Decimal("10"),
                revenue=Decimal("30"),
            ),
            AdCampaign(
                product_id=product_id,
                platform="Instagram",
                campaign_name="Conversion",
                date=date(2026, 7, 2),
                impressions=900,
                clicks=40,
                conversions=9,
                spend=Decimal("90"),
                revenue=Decimal("270"),
            ),
        ]
    )
    db_session.commit()
    fake_provider = FakeGrowthProvider()
    app.dependency_overrides[get_text_generation_provider] = lambda: fake_provider
    try:
        response = client.post(f"/api/v1/products/{product_id}/growth-analysis")
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"] == {
        "impressions": 1000,
        "clicks": 50,
        "conversions": 10,
        "spend": 100.0,
        "revenue": 300.0,
        "ctr": 0.05,
        "conversion_rate": 0.2,
        "cpa": 10.0,
        "roas": 3.0,
    }
    assert body["recommendation"]["problems"] == [
        "CTR trails the campaign target."
    ]
    assert fake_provider.calls == 1
