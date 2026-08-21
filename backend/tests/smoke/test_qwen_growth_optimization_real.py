from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models import AdCampaign, CopyMatrix, MarketingStrategy, Product, VideoProject
from app.providers import TextGenerationProvider
from app.providers.live_configuration import effective_qwen_api_key
from app.providers.qwen_provider import QwenProvider
from app.schemas.growth import GrowthOptimizationRunCreateRequest
from app.services.feedback_context_service import FeedbackContextService
from app.services.growth_analysis_service import GrowthAnalysisService
from app.services.growth_optimization_run_service import GrowthOptimizationRunService
from app.services.growth_recommendation_preflight import (
    GrowthRecommendationPreflightService,
)

pytestmark = [pytest.mark.smoke, pytest.mark.qwen_smoke]


def _new_path(name: str) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value)
    if not value or not path.is_absolute() or not path.parent.is_dir():
        pytest.fail(f"{name} must be in an existing absolute directory")
    if path.exists():
        pytest.fail(f"{name} must point to a new file")
    return path


class _CountingQwen(TextGenerationProvider):
    def __init__(self, live_settings: object) -> None:
        self.provider = QwenProvider(live_settings)  # type: ignore[arg-type]
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        assert self.calls == 1
        return self.provider.generate(prompt)


def test_qwen_real_roas_optimization_plan() -> None:
    if not effective_qwen_api_key(settings):
        pytest.skip("Token Plan credentials are not configured")
    output_path = _new_path("QWEN_GROWTH_OUTPUT")
    database_path = _new_path("QWEN_GROWTH_DATABASE")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    live_settings = settings.model_copy(update={"enable_growth_execution": True})

    with sessions() as session:
        product = Product(
            name="Fictional teal portable blender",
            category="Portable kitchen appliance",
            description="A cordless blender for fresh drinks away from home.",
            selling_points=["Portable", "Rechargeable", "Easy to clean"],
            target_markets=["US"],
        )
        session.add(product)
        session.flush()
        strategy = MarketingStrategy(
            product_id=product.id,
            positioning="Fresh smoothies anywhere in seconds",
            audience_insights=["Busy commuters value convenience"],
            angles=["Portable fresh-drink routine"],
            risks=["No unsupported claims"],
            evidence=["Portable", "Rechargeable", "Easy to clean"],
        )
        session.add(strategy)
        session.flush()
        matrix = CopyMatrix(
            product_id=product.id,
            marketing_strategy_id=strategy.id,
            copies=[
                {
                    "platform": platform,
                    "hook": f"{platform} portable routine",
                    "caption": "A practical portable blender for busy days.",
                    "hashtags": ["#PortableBlender"],
                    "cta": "Learn more",
                }
                for platform in ("TikTok", "Instagram", "Facebook", "Pinterest")
            ],
        )
        session.add(matrix)
        session.flush()
        project = VideoProject(
            product_id=product.id,
            marketing_strategy_id=strategy.id,
            copy_matrix_id=matrix.id,
            platform="TikTok",
            title="Portable blender routine",
            concept="Show one controlled daily use case.",
            duration_seconds=15,
            aspect_ratio="9:16",
            scenes=[
                {
                    "sequence": 1,
                    "duration_seconds": 15,
                    "shot_type": "Product",
                    "visual_description": "The exact portable blender",
                    "action": "Prepare a fresh drink",
                    "narration": "Fresh drinks fit busy routines.",
                }
            ],
            cta="Learn more",
            status="planned",
        )
        session.add(project)
        for platform, spend, revenue in (
            ("TikTok", "100", "500"),
            ("Instagram", "100", "250"),
            ("Facebook", "100", "180"),
            ("Pinterest", "100", "60"),
        ):
            session.add(
                AdCampaign(
                    product_id=product.id,
                    platform=platform,
                    campaign_name=f"{platform} controlled campaign",
                    date=date(2026, 8, 21),
                    impressions=10_000,
                    clicks=500,
                    conversions=50,
                    spend=Decimal(spend),
                    revenue=Decimal(revenue),
                )
            )
        session.commit()

        checked = GrowthRecommendationPreflightService(session, live_settings).run(
            product.id
        )
        assert checked.ready_for_execution is True
        provider = _CountingQwen(live_settings)
        analysis = GrowthAnalysisService(session, provider, live_settings).analyze(
            product.id, checked.context_digest
        )
        created = GrowthOptimizationRunService(session).create(
            product.id,
            GrowthOptimizationRunCreateRequest(
                analysis=analysis,
                policy={
                    "total_budget": 400,
                    "target_roas": 2,
                    "minimum_platform_share": 0.05,
                    "performance_tilt_share": 0.15,
                    "maximum_bid_adjustment_pct": 0.2,
                },
                idempotency_key="real-qwen-growth-plan-1",
                activate_internal=True,
            ),
        )
        assert provider.calls == 1
        assert created.reused is False
        assert created.run.status == "ACTIVE"
        assert created.run.execution_scope == "INTERNAL_PLAN_ONLY"
        assert created.run.external_execution_status == "NOT_CONNECTED"
        assert len(created.run.actions) == 4
        assert (
            round(sum(item.recommended_budget for item in created.run.actions), 2)
            == 400
        )
        assert {item.platform for item in created.run.actions} == {
            "TikTok",
            "Instagram",
            "Facebook",
            "Pinterest",
        }
        context = FeedbackContextService(session).get(product.id)
        assert context.context_digest == created.run.source_context_digest
        evidence = {
            "provider_calls": provider.calls,
            "provider_model": live_settings.qwen_model,
            "product_id": product.id,
            "campaign_ids": context.campaign_ids,
            "context_digest": context.context_digest,
            "recommendation_digest": analysis.recommendation_digest,
            "optimization_run_id": created.run.id,
            "optimization_status": created.run.status,
            "execution_scope": created.run.execution_scope,
            "external_execution_status": created.run.external_execution_status,
            "recommended_total_budget": created.run.recommended_total_budget,
            "actions": [item.model_dump(mode="json") for item in created.run.actions],
        }

    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    engine.dispose()
    print(
        json.dumps(
            {
                "provider_calls": evidence["provider_calls"],
                "optimization_status": evidence["optimization_status"],
                "platforms": [item["platform"] for item in evidence["actions"]],
            },
            sort_keys=True,
        )
    )
