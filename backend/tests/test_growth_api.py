import json
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.main import app
from app.models import (
    AdCampaign,
    CopyMatrix,
    MarketingStrategy,
    VideoProject,
)
from app.providers.base import TextGenerationProvider
from app.services.growth_analysis_service import GrowthAnalysisService


class FakeGrowthProvider(TextGenerationProvider):
    calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        assert '"calculated_feedback_context"' in prompt
        assert '"impressions":1000' in prompt
        assert '"ctr":0.05' in prompt
        assert "campaign_name" not in prompt
        return json.dumps(
            {
                "summary": "Test stronger opening clarity without claiming causality.",
                "observations": [
                    {
                        "scope": "overall",
                        "platform": None,
                        "metric": "ctr",
                        "direction": "test",
                        "hypothesis": "A clearer opening may improve attention.",
                    }
                ],
                "copy_constraints": [
                    {
                        "platform": "TikTok",
                        "hook_direction": "Lead with portable use.",
                        "message_angle": "Convenience during a busy day.",
                        "cta_direction": "Invite a controlled product test.",
                        "must_preserve": ["USB rechargeable"],
                        "must_avoid": ["Causal performance claims"],
                    }
                ],
                "video_constraint": {
                    "platform": "TikTok",
                    "opening_hook_direction": "Show the use case immediately.",
                    "visual_focus": "Portable blender in a real routine.",
                    "pacing_direction": "Keep the opening concise.",
                    "cta_direction": "Invite viewers to learn more.",
                    "must_preserve": ["Product visibility"],
                    "must_avoid": ["Guaranteed outcomes"],
                },
                "budget_guidance": "Keep budget unchanged while testing.",
            }
        )


def test_growth_api_returns_aggregate_metrics_and_mock_analysis(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = client.post("/api/v1/products", json=product_payload).json()["id"]
    strategy = MarketingStrategy(
        product_id=product_id,
        positioning="Portable daily nutrition.",
        audience_insights=["Busy professionals value convenience."],
        angles=["Blend anywhere"],
        risks=["Avoid health guarantees."],
        evidence=["USB rechargeable."],
    )
    db_session.add(strategy)
    db_session.flush()
    copy_matrix = CopyMatrix(
        product_id=product_id,
        marketing_strategy_id=strategy.id,
        copies=[
            {
                "platform": platform,
                "hook": "Hook",
                "caption": "Caption",
                "hashtags": ["#Safe"],
                "cta": "CTA",
            }
            for platform in ("TikTok", "Instagram", "Facebook")
        ],
    )
    db_session.add(copy_matrix)
    db_session.flush()
    db_session.add(
        VideoProject(
            product_id=product_id,
            marketing_strategy_id=strategy.id,
            copy_matrix_id=copy_matrix.id,
            platform="TikTok",
            title="Portable routine",
            concept="Show one controlled product use case.",
            duration_seconds=10,
            aspect_ratio="9:16",
            scenes=[
                {
                    "sequence": 1,
                    "duration_seconds": 10,
                    "shot_type": "Product",
                    "visual_description": "Portable blender",
                    "action": "Blend a drink",
                    "narration": "Blend anywhere",
                }
            ],
            cta="Learn more",
            status="planned",
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
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        enable_growth_execution=True,
        dashscope_api_key="fake-test-key",
    )
    try:
        digest = client.get(
            f"/api/v1/products/{product_id}/feedback-context"
        ).json()["context_digest"]
        response = client.post(
            f"/api/v1/products/{product_id}/growth-analysis",
            json={"expected_context_digest": digest},
        )
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    body = response.json()
    assert body["source_context_digest"] == digest
    assert body["source_marketing_strategy_id"] == strategy.id
    assert body["source_copy_matrix_id"] == copy_matrix.id
    assert body["recommendation"]["observations"][0]["metric"] == "ctr"
    assert body["recommendation_persisted"] is False
    assert body["automatic_action_allowed"] is False
    assert body["copy_generation_triggered"] is False
    assert body["video_generation_triggered"] is False
    assert fake_provider.calls == 1


def test_growth_api_default_gate_blocks_before_provider_resolution_and_write(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = client.post("/api/v1/products", json=product_payload).json()["id"]
    provider_resolutions = 0
    original_campaign_count = db_session.query(AdCampaign).count()
    original_strategy_count = db_session.query(MarketingStrategy).count()

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("disabled Growth route resolved a Provider")

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    try:
        response = client.post(
            f"/api/v1/products/{product_id}/growth-analysis"
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 503
    assert response.json()["error"]["message"] == (
        "Growth analysis execution is disabled by the server"
    )
    assert provider_resolutions == 0
    assert db_session.query(AdCampaign).count() == original_campaign_count
    assert (
        db_session.query(MarketingStrategy).count()
        == original_strategy_count
    )


def test_growth_service_default_gate_cannot_be_bypassed(
    db_session: Session,
) -> None:
    provider = FakeGrowthProvider()
    service = GrowthAnalysisService(
        db_session,
        provider,
        Settings(_env_file=None),
    )

    try:
        service.analyze(999, "0" * 64)
    except AppError as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("direct service call bypassed Growth gate")

    assert provider.calls == 0
