import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.providers import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderModelError,
    TextGenerationProvider,
)
from app.repositories.campaign import CampaignRepository
from app.repositories.product import ProductRepository
from app.repositories.strategy import MarketingStrategyRepository
from app.schemas.campaign import CampaignMetricsSchema
from app.schemas.growth import GrowthAnalysisResponse, GrowthRecommendation
from app.services.metrics_service import MetricsService


class GrowthAnalysisService:
    def __init__(
        self, session: Session, provider: TextGenerationProvider
    ) -> None:
        self.product_repository = ProductRepository(session)
        self.campaign_repository = CampaignRepository(session)
        self.strategy_repository = MarketingStrategyRepository(session)
        self.provider = provider

    def analyze(self, product_id: int) -> GrowthAnalysisResponse:
        if self.product_repository.get(product_id) is None:
            raise AppError("Product not found", status_code=404)

        campaigns = self.campaign_repository.list_by_product(product_id)
        if not campaigns:
            raise AppError("Campaign data must be uploaded first", status_code=409)

        strategy = self.strategy_repository.get_latest_by_product(product_id)
        if strategy is None:
            raise AppError(
                "Marketing strategy must be generated first", status_code=409
            )

        metrics = MetricsService.calculate(campaigns)
        strategy_data = {
            "positioning": strategy.positioning,
            "audience_insights": strategy.audience_insights,
            "angles": strategy.angles,
            "risks": strategy.risks,
            "evidence": strategy.evidence,
        }
        try:
            raw_result = self.provider.generate(
                self._build_prompt(metrics, strategy_data)
            )
        except ProviderAuthenticationError as exc:
            raise AppError("Qwen authentication failed", status_code=502) from exc
        except ProviderConnectionError as exc:
            raise AppError("Qwen service is unavailable", status_code=503) from exc
        except ProviderModelError as exc:
            raise AppError("Qwen generation failed", status_code=502) from exc

        try:
            recommendation = GrowthRecommendation.model_validate_json(raw_result)
        except (ValidationError, ValueError) as exc:
            raise AppError(
                "Qwen returned invalid growth analysis data", status_code=502
            ) from exc

        return GrowthAnalysisResponse(
            metrics=metrics, recommendation=recommendation
        )

    @staticmethod
    def _build_prompt(
        metrics: CampaignMetricsSchema, strategy: dict[str, object]
    ) -> str:
        context = {
            "calculated_metrics": metrics.model_dump(mode="json"),
            "marketing_strategy": strategy,
        }
        return (
            "Analyze only the already-calculated advertising metrics and the "
            "provided marketing strategy. Do not recalculate CTR, conversion "
            "rate, CPA, or ROAS. Return one JSON object with exactly these "
            "required fields: problems (non-empty string array), recommendations "
            "(non-empty string array), budget_suggestion (non-empty string), and "
            "creative_suggestions (non-empty string array). Recommendations are "
            "advisory only; do not claim that budgets or campaigns were changed. "
            "Context:\n"
            f"{json.dumps(context, ensure_ascii=False)}"
        )
