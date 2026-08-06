from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import MarketingStrategy, Product
from app.providers.live_configuration import effective_qwen_api_key
from app.repositories.marketing import MarketingRepository
from app.repositories.strategy import MarketingStrategyRepository
from app.schemas.copy import (
    CopyPreflightProductSummary,
    CopyPreflightRead,
    CopyPreflightStrategySummary,
)
from app.schemas.marketing import SUPPORTED_MARKETING_PLATFORMS
from app.schemas.strategy import MarketingStrategySchema
from app.services.marketing import TARGET_MARKET_AUDIENCE_PATTERN

COPY_ASSOCIATION_NOTICE = (
    "Task-bound execution persists the exact Strategy through "
    "marketing_strategy_id. MarketingBrief association remains response-only "
    "because CopyMatrix has no MarketingBrief foreign key."
)
COPY_COST_NOTICE = (
    "真实Copy生成将调用阿里云百炼Qwen，并可能消耗比赛Credits；"
    "实际消耗由模型、输入输出长度和平台计费决定。"
)


class CopyPreflightService:
    """Validate exact Brief and Strategy inputs without resolving a Provider."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.marketing_repository = MarketingRepository(session)
        self.strategy_repository = MarketingStrategyRepository(session)

    def run(self, task_id: int, strategy_id: int) -> CopyPreflightRead:
        task = self.marketing_repository.get(task_id)
        if task is None:
            raise AppError("Marketing task not found", status_code=404)

        strategy = self.strategy_repository.get(strategy_id)
        if strategy is None:
            raise AppError("Marketing strategy not found", status_code=404)

        task_product = self.session.get(Product, task.product_id)
        if task_product is None:
            raise AppError("Marketing task Product not found", status_code=404)

        strategy_product = self.session.get(Product, strategy.product_id)
        if strategy_product is None:
            raise AppError("Marketing strategy Product not found", status_code=404)

        if task.product_id != strategy.product_id:
            raise AppError(
                "Marketing task and Strategy belong to different Products",
                status_code=409,
            )

        normalized_platforms = self._normalize_platforms(task.platforms)
        missing, strategy_data = self._input_requirements(
            task_product,
            strategy,
            normalized_platforms,
            task.audience,
        )
        provider_configured = self._provider_configured()
        if not provider_configured:
            missing.append("provider_configuration")
        if not self.settings.enable_copy_execution:
            missing.append("copy_execution")

        contract_ready = True

        input_requirements = {
            "product_name",
            "product_category",
            "product_description",
            "product_selling_points",
            "strategy_schema",
            "supported_platforms",
            "target_market_snapshot",
        }
        input_ready = not any(item in input_requirements for item in missing)
        ready_for_execution = (
            input_ready
            and provider_configured
            and self.settings.enable_copy_execution
            and contract_ready
        )
        return CopyPreflightRead(
            task_id=task.id,
            strategy_id=strategy.id,
            product_id=task_product.id,
            ready=ready_for_execution,
            input_ready=input_ready,
            provider_configured=provider_configured,
            execution_enabled=self.settings.enable_copy_execution,
            contract_ready=contract_ready,
            ready_for_execution=ready_for_execution,
            missing_requirements=missing,
            platforms=normalized_platforms or [],
            product_summary=CopyPreflightProductSummary(
                id=task_product.id,
                name=task_product.name or "",
                category=task_product.category or "",
                description=task_product.description or "",
                selling_points=list(task_product.selling_points or []),
            ),
            strategy_summary=CopyPreflightStrategySummary(
                id=strategy.id,
                positioning=(
                    strategy_data.positioning
                    if strategy_data is not None
                    else str(strategy.positioning or "").strip()
                ),
                audience_insights_count=len(strategy.audience_insights or []),
                angles_count=len(strategy.angles or []),
                risks_count=len(strategy.risks or []),
                evidence_count=len(strategy.evidence or []),
            ),
            association_notice=COPY_ASSOCIATION_NOTICE,
            cost_notice=COPY_COST_NOTICE,
        )

    def _provider_configured(self) -> bool:
        return bool(effective_qwen_api_key(self.settings))

    @staticmethod
    def _input_requirements(
        product: Product,
        strategy: MarketingStrategy,
        platforms: list[str] | None,
        task_audience: str | None,
    ) -> tuple[list[str], MarketingStrategySchema | None]:
        missing: list[str] = []
        for name, value in (
            ("product_name", product.name),
            ("product_category", product.category),
            ("product_description", product.description),
        ):
            if not str(value or "").strip():
                missing.append(name)
        if not product.selling_points or any(
            not str(point).strip() for point in product.selling_points
        ):
            missing.append("product_selling_points")

        strategy_data: MarketingStrategySchema | None = None
        try:
            strategy_data = MarketingStrategySchema.model_validate(strategy)
        except ValidationError:
            missing.append("strategy_schema")

        if not platforms:
            missing.append("supported_platforms")

        market_match = TARGET_MARKET_AUDIENCE_PATTERN.match(task_audience or "")
        if market_match is None or not any(
            market.strip() for market in market_match.group(1).split(",")
        ):
            missing.append("target_market_snapshot")
        return missing, strategy_data

    @staticmethod
    def _normalize_platforms(
        platforms: list[str] | None,
    ) -> list[str] | None:
        if not platforms or not 1 <= len(platforms) <= 3:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for value in platforms:
            key = str(value).strip().casefold()
            canonical = SUPPORTED_MARKETING_PLATFORMS.get(key)
            if canonical is None or key in seen:
                return None
            normalized.append(canonical)
            seen.add(key)
        return normalized
