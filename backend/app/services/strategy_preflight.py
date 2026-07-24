from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import MarketingBrief, Product
from app.providers.qwen_provider import QwenProvider
from app.repositories.marketing import MarketingRepository
from app.schemas.marketing import SUPPORTED_MARKETING_PLATFORMS
from app.schemas.strategy import (
    StrategyPreflightProductSummary,
    StrategyPreflightRead,
)
from app.services.marketing import TARGET_MARKET_AUDIENCE_PATTERN
from app.services.marketing_strategy_service import MarketingStrategyService

PROVIDER_LABEL = "Alibaba Cloud Bailian Qwen"
COST_NOTICE = (
    "执行真实生成将调用阿里云百炼 Qwen，并可能消耗比赛 Credits；"
    "实际消耗由模型、输入输出长度和平台计费决定。"
)


class StrategyPreflightService:
    """Validate strategy inputs without instantiating or calling a Provider."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        provider_type: type[object] | None = QwenProvider,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider_type = provider_type
        self.marketing_repository = MarketingRepository(session)

    def run(self, task_id: int) -> StrategyPreflightRead:
        task = self.marketing_repository.get(task_id)
        if task is None:
            raise AppError("Marketing task not found", status_code=404)

        product = self.session.get(Product, task.product_id)
        if product is None:
            raise AppError("Product not found", status_code=404)
        if task.product_id != product.id:
            raise AppError(
                "Marketing task Product association is invalid", status_code=409
            )

        audience_value = task.audience or ""
        market_match = TARGET_MARKET_AUDIENCE_PATTERN.match(audience_value)
        target_market_snapshot = (
            market_match.group(1).split(",")
            if market_match is not None
            else list(product.target_markets or [])
        )
        product_input = MarketingStrategyService.prepare_product_input(product)
        provider_type_available = isinstance(self.provider_type, type)
        provider_configured = self._provider_configured()
        missing = self._missing_requirements(
            task,
            product_input,
            target_market_snapshot=target_market_snapshot,
            provider_type_available=provider_type_available,
            provider_configured=provider_configured,
        )
        audience = TARGET_MARKET_AUDIENCE_PATTERN.sub("", audience_value).strip()

        return StrategyPreflightRead(
            task_id=task.id,
            product_id=product.id,
            ready=not missing,
            missing_requirements=missing,
            product_summary=StrategyPreflightProductSummary(
                id=product.id,
                name=str(product_input["name"] or ""),
                category=str(product_input["category"] or ""),
                description=str(product_input["description"] or ""),
                selling_points=list(product_input["selling_points"] or []),
            ),
            target_market_snapshot=target_market_snapshot,
            platforms=list(task.platforms or []),
            audience=audience,
            language=task.language or "",
            tone=task.tone or "",
            objective=task.objective or "",
            provider_label=PROVIDER_LABEL,
            model_label=self.settings.qwen_model,
            provider_configured=provider_configured,
            cost_notice=COST_NOTICE,
        )

    def _provider_configured(self) -> bool:
        secret = self.settings.dashscope_api_key
        return bool(secret and secret.get_secret_value().strip())

    @staticmethod
    def _missing_requirements(
        task: MarketingBrief,
        product_input: dict[str, object],
        *,
        target_market_snapshot: list[str],
        provider_type_available: bool,
        provider_configured: bool,
    ) -> list[str]:
        missing: list[str] = []
        if not str(product_input["name"] or "").strip():
            missing.append("product_name")
        if not str(product_input["category"] or "").strip():
            missing.append("product_category")
        if not str(product_input["description"] or "").strip():
            missing.append("product_description")
        selling_points = product_input["selling_points"]
        if not isinstance(selling_points, list) or not selling_points or any(
            not str(point).strip() for point in selling_points
        ):
            missing.append("product_selling_points")
        if not target_market_snapshot:
            missing.append("target_market_snapshot")
        supported = set(SUPPORTED_MARKETING_PLATFORMS.values())
        normalized_platforms = [
            platform.strip() for platform in (task.platforms or [])
        ]
        if (
            not normalized_platforms
            or len(normalized_platforms) > 3
            or len({platform.casefold() for platform in normalized_platforms})
            != len(normalized_platforms)
            or any(platform not in supported for platform in normalized_platforms)
        ):
            missing.append("supported_platforms")
        audience = TARGET_MARKET_AUDIENCE_PATTERN.sub(
            "", task.audience or ""
        ).strip()
        for field_name, value in (
            ("audience", audience),
            ("language", task.language or ""),
            ("tone", task.tone or ""),
            ("objective", task.objective or ""),
        ):
            if not value.strip():
                missing.append(field_name)
        if not provider_type_available:
            missing.append("qwen_provider_type")
        if not provider_configured:
            missing.append("provider_configuration")
        return missing
