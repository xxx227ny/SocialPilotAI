import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import CopyMatrix, MarketingStrategy, Product
from app.providers.live_configuration import (
    qwen_missing_requirements,
    qwen_provider_configured,
)
from app.repositories.copy import CopyMatrixRepository
from app.repositories.product import ProductRepository
from app.repositories.strategy import MarketingStrategyRepository
from app.schemas.copy import TaskBoundCopyMatrixSchema
from app.schemas.strategy import MarketingStrategySchema
from app.schemas.video import (
    INITIAL_VIDEO_PROJECT_CONTRACT_VERSION,
    InitialVideoProjectPreflightRead,
    InitialVideoProjectSourceRead,
    InitialVideoProjectSourceRequest,
)

INITIAL_VIDEO_PROJECT_PREFLIGHT_TTL = timedelta(minutes=10)
INITIAL_VIDEO_PROJECT_COST_NOTICE = (
    "Creating the first Video Blueprint calls Qwen once and may incur "
    "provider charges. It does not call Wanx or render media."
)
INITIAL_VIDEO_PROJECT_ASSOCIATION_NOTICE = (
    "The VideoProject persistently references the exact Product, "
    "MarketingStrategy, and CopyMatrix confirmed by this Preflight."
)


class InitialVideoProjectSourceQueryService:
    """Discover one exact, read-only source chain without resolving a Provider."""

    def __init__(self, session: Session) -> None:
        self.copy_repository = CopyMatrixRepository(session)

    def get_for_product(self, product_id: int) -> InitialVideoProjectSourceRead:
        source = self.copy_repository.get_latest_valid_source_chain(product_id)
        if source is None:
            raise AppError(
                "No valid Strategy and CopyMatrix source chain found",
                status_code=404,
            )
        product, strategy, copy_matrix = source
        return InitialVideoProjectSourceRead(
            product_id=product.id,
            strategy_id=strategy.id,
            copy_matrix_id=copy_matrix.id,
        )


class InitialVideoProjectPreflightService:
    """Validate an exact first-VideoProject operation without a Provider."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.now = now or (lambda: datetime.now(UTC))
        self.product_repository = ProductRepository(session)
        self.strategy_repository = MarketingStrategyRepository(session)
        self.copy_repository = CopyMatrixRepository(session)

    def run(
        self,
        product_id: int,
        data: InitialVideoProjectSourceRequest,
        *,
        expires_at: datetime | None = None,
    ) -> InitialVideoProjectPreflightRead:
        product = self.product_repository.get(product_id)
        if product is None:
            raise AppError("Product not found", status_code=404)
        strategy = self.strategy_repository.get(data.strategy_id)
        if strategy is None:
            raise AppError("Marketing strategy not found", status_code=404)
        copy_matrix = self.copy_repository.get(data.copy_matrix_id)
        if copy_matrix is None:
            raise AppError("Copy matrix not found", status_code=404)

        missing: list[str] = []
        if not self._product_ready(product):
            missing.append("product_input")
        if not self._strategy_ready(strategy):
            missing.append("strategy_schema")
        if not self._copy_ready(copy_matrix):
            missing.append("copy_matrix_schema")
        if not self._same_chain(product, strategy, copy_matrix):
            missing.append("source_association")
        if not self._copy_has_platform(copy_matrix, data.platform):
            missing.append("platform_copy")

        provider_configured = qwen_provider_configured(self.settings)
        if not provider_configured:
            missing.append("provider_configuration")
            missing.extend(qwen_missing_requirements(self.settings))
        execution_enabled = self.settings.enable_video_project_execution
        if not execution_enabled:
            missing.append("video_project_execution")

        input_requirements = {
            "product_input",
            "strategy_schema",
            "copy_matrix_schema",
            "source_association",
            "platform_copy",
        }
        input_ready = not any(item in input_requirements for item in missing)
        normalized_expiry = self._normalize_expiry(
            expires_at or self.now() + INITIAL_VIDEO_PROJECT_PREFLIGHT_TTL
        )
        digest = self.compute_preflight_digest(
            product=product,
            strategy=strategy,
            copy_matrix=copy_matrix,
            request=data,
            expires_at=normalized_expiry,
        )
        return InitialVideoProjectPreflightRead(
            product_id=product.id,
            strategy_id=strategy.id,
            copy_matrix_id=copy_matrix.id,
            platform=data.platform,
            duration_seconds=data.duration_seconds,
            aspect_ratio=data.aspect_ratio,
            input_ready=input_ready,
            provider_configured=provider_configured,
            execution_enabled=execution_enabled,
            contract_ready=True,
            ready_for_execution=(
                input_ready and provider_configured and execution_enabled
            ),
            missing_requirements=list(dict.fromkeys(missing)),
            preflight_digest=digest,
            expires_at=normalized_expiry,
            cost_notice=INITIAL_VIDEO_PROJECT_COST_NOTICE,
            association_notice=INITIAL_VIDEO_PROJECT_ASSOCIATION_NOTICE,
        )

    @staticmethod
    def compute_preflight_digest(
        *,
        product: Product,
        strategy: MarketingStrategy,
        copy_matrix: CopyMatrix,
        request: InitialVideoProjectSourceRequest,
        expires_at: datetime,
    ) -> str:
        payload = {
            "contract_version": INITIAL_VIDEO_PROJECT_CONTRACT_VERSION,
            "expires_at": InitialVideoProjectPreflightService._normalize_expiry(
                expires_at
            ).isoformat(),
            "request": request.model_dump(mode="json"),
            "product": {
                "id": product.id,
                "name": product.name,
                "category": product.category,
                "description": product.description,
                "selling_points": list(product.selling_points or []),
                "target_markets": list(product.target_markets or []),
            },
            "strategy": {
                "id": strategy.id,
                "product_id": strategy.product_id,
                "positioning": strategy.positioning,
                "audience_insights": list(strategy.audience_insights or []),
                "angles": list(strategy.angles or []),
                "risks": list(strategy.risks or []),
                "evidence": list(strategy.evidence or []),
            },
            "copy_matrix": {
                "id": copy_matrix.id,
                "product_id": copy_matrix.product_id,
                "marketing_strategy_id": copy_matrix.marketing_strategy_id,
                "copies": copy_matrix.copies or [],
            },
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _product_ready(product: Product) -> bool:
        return bool(
            product.name.strip()
            and (product.category or "").strip()
            and (product.description or "").strip()
            and product.selling_points
            and all(str(item).strip() for item in product.selling_points)
        )

    @staticmethod
    def _strategy_ready(strategy: MarketingStrategy) -> bool:
        try:
            MarketingStrategySchema.model_validate(strategy)
        except ValidationError:
            return False
        return True

    @staticmethod
    def _copy_ready(copy_matrix: CopyMatrix) -> bool:
        try:
            TaskBoundCopyMatrixSchema.model_validate(copy_matrix)
        except ValidationError:
            return False
        return True

    @staticmethod
    def _same_chain(
        product: Product,
        strategy: MarketingStrategy,
        copy_matrix: CopyMatrix,
    ) -> bool:
        return bool(
            strategy.product_id == product.id
            and copy_matrix.product_id == product.id
            and copy_matrix.marketing_strategy_id == strategy.id
        )

    @staticmethod
    def _copy_has_platform(copy_matrix: CopyMatrix, platform: str) -> bool:
        return any(
            isinstance(item, dict)
            and str(item.get("platform", "")).casefold() == platform.casefold()
            for item in (copy_matrix.copies or [])
        )

    @staticmethod
    def _normalize_expiry(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Preflight expiry must include a timezone")
        return value.astimezone(UTC)
