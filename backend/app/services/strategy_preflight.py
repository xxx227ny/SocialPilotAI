import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import MarketingBrief, Product
from app.providers.live_configuration import effective_qwen_api_key
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
STRATEGY_PREFLIGHT_TTL = timedelta(minutes=10)
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
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider_type = provider_type
        self.now = now or (lambda: datetime.now(UTC))
        self.marketing_repository = MarketingRepository(session)

    def run(
        self, task_id: int, *, expires_at: datetime | None = None
    ) -> StrategyPreflightRead:
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
            market_match.group(1).split(",") if market_match is not None else []
        )
        product_input = MarketingStrategyService.prepare_product_input(product)
        provider_type_available = isinstance(self.provider_type, type)
        provider_configured = self._provider_configured()
        input_missing = self._missing_requirements(
            task,
            product_input,
            target_market_snapshot=target_market_snapshot,
            provider_type_available=provider_type_available,
        )
        missing = list(input_missing)
        if not provider_configured:
            missing.append("provider_configuration")
        if not self.settings.enable_strategy_execution:
            missing.append("strategy_execution")
        input_ready = not input_missing
        ready_for_execution = (
            input_ready
            and provider_configured
            and self.settings.enable_strategy_execution
        )
        audience = TARGET_MARKET_AUDIENCE_PATTERN.sub("", audience_value).strip()
        input_digest = self.compute_input_digest(
            product=product,
            task=task,
            model_label=self.settings.qwen_model,
        )
        normalized_expiry = self._normalize_expiry(
            expires_at or self.now() + STRATEGY_PREFLIGHT_TTL
        )
        preflight_digest = self.compute_preflight_digest(
            input_digest=input_digest,
            expires_at=normalized_expiry,
        )

        return StrategyPreflightRead(
            task_id=task.id,
            product_id=product.id,
            ready=ready_for_execution,
            input_ready=input_ready,
            ready_for_execution=ready_for_execution,
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
            execution_enabled=self.settings.enable_strategy_execution,
            input_digest=input_digest,
            preflight_digest=preflight_digest,
            expires_at=normalized_expiry,
            cost_notice=COST_NOTICE,
        )

    @staticmethod
    def compute_input_digest(
        *, product: Product, task: MarketingBrief, model_label: str
    ) -> str:
        payload = {
            "schema": "qwen.strategy.generate.v1",
            "product": MarketingStrategyService.prepare_product_input(product),
            "marketing_brief": MarketingStrategyService.prepare_marketing_brief_input(
                product, task
            )["marketing_brief"],
            "model": model_label,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def compute_preflight_digest(*, input_digest: str, expires_at: datetime) -> str:
        payload = {
            "input_digest": input_digest,
            "expires_at": StrategyPreflightService._normalize_expiry(
                expires_at
            ).isoformat(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _normalize_expiry(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Strategy preflight expiry requires a timezone")
        return value.astimezone(UTC)

    def _provider_configured(self) -> bool:
        return bool(effective_qwen_api_key(self.settings))

    @staticmethod
    def _missing_requirements(
        task: MarketingBrief,
        product_input: dict[str, object],
        *,
        target_market_snapshot: list[str],
        provider_type_available: bool,
    ) -> list[str]:
        missing: list[str] = []
        if not str(product_input["name"] or "").strip():
            missing.append("product_name")
        if not str(product_input["category"] or "").strip():
            missing.append("product_category")
        if not str(product_input["description"] or "").strip():
            missing.append("product_description")
        selling_points = product_input["selling_points"]
        if (
            not isinstance(selling_points, list)
            or not selling_points
            or any(not str(point).strip() for point in selling_points)
        ):
            missing.append("product_selling_points")
        if not target_market_snapshot:
            missing.append("target_market_snapshot")
        supported = set(SUPPORTED_MARKETING_PLATFORMS.values())
        normalized_platforms = [platform.strip() for platform in (task.platforms or [])]
        if (
            not normalized_platforms
            or len(normalized_platforms) > len(supported)
            or len({platform.casefold() for platform in normalized_platforms})
            != len(normalized_platforms)
            or any(platform not in supported for platform in normalized_platforms)
        ):
            missing.append("supported_platforms")
        audience = TARGET_MARKET_AUDIENCE_PATTERN.sub("", task.audience or "").strip()
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
        return missing
