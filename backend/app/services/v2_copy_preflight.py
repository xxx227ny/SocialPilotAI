import hashlib
import json

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CopyMatrix, MarketingStrategy, Product, VideoProject
from app.repositories.product import ProductRepository
from app.schemas.copy import (
    V2_COPY_CONTRACT_VERSION,
    V2CopyPreflightRead,
    V2CopySourceRequest,
)
from app.schemas.growth import compute_recommendation_digest
from app.services.feedback_context_service import FeedbackContextService

V2_COPY_COST_NOTICE = (
    "生成V2 Copy Candidate将调用阿里云百炼Qwen，并可能产生费用；"
    "具体消耗以模型、输入输出长度和平台实际计费为准。"
)
V2_COPY_ASSOCIATION_NOTICE = (
    "新CopyMatrix仅持久化Product与精确MarketingStrategy关联。"
    "Recommendation、FeedbackContext、源Copy父子关系和版本标签均未持久化。"
)


class V2CopyPreflightService:
    """Validate one Recommendation-bound Copy operation without a Provider."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.settings = settings
        self.feedback_service = FeedbackContextService(session)
        self.product_repository = ProductRepository(session)

    def run(
        self, product_id: int, data: V2CopySourceRequest
    ) -> V2CopyPreflightRead:
        context, strategy, copy_matrix, video_project = (
            self.feedback_service.get_with_validated_chain(product_id)
        )
        product = self.product_repository.get(product_id)
        # FeedbackContext already returns 404 for a missing Product.
        assert product is not None

        target_platforms = [
            item.platform for item in data.recommendation.copy_constraints
        ]
        calculated_recommendation_digest = compute_recommendation_digest(
            product_id=product_id,
            source_context_digest=data.source_context_digest,
            source_marketing_strategy_id=data.source_marketing_strategy_id,
            source_copy_matrix_id=data.source_copy_matrix_id,
            source_video_project_id=data.source_video_project_id,
            recommendation=data.recommendation,
        )
        missing: list[str] = []
        if not context.context_ready:
            missing.extend(context.missing_requirements)
        if context.context_digest != data.source_context_digest:
            missing.append("stale_context_digest")
        if calculated_recommendation_digest != data.recommendation_digest:
            missing.append("recommendation_digest_mismatch")
        if not self._same_chain(
            data,
            strategy,
            copy_matrix,
            video_project,
            product_id,
        ):
            missing.append("source_content_chain_mismatch")
        if not self._target_platforms_valid(target_platforms, copy_matrix):
            missing.append("recommendation_copy_platforms")
        if not self._product_ready(product):
            missing.append("product_input")

        provider_configured = self._provider_configured()
        if not provider_configured:
            missing.append("provider_configuration")
        if not self.settings.enable_copy_execution:
            missing.append("copy_execution")
        if not self.settings.enable_v2_copy_execution:
            missing.append("v2_copy_execution")

        input_missing = {
            "campaign_data",
            "video_project",
            "marketing_strategy",
            "copy_matrix",
            "exact_content_chain",
            "stale_context_digest",
            "recommendation_digest_mismatch",
            "source_content_chain_mismatch",
            "recommendation_copy_platforms",
            "product_input",
        }
        input_ready = not any(item in input_missing for item in missing)
        contract_ready = True
        ready_for_execution = all(
            (
                input_ready,
                provider_configured,
                self.settings.enable_copy_execution,
                self.settings.enable_v2_copy_execution,
                contract_ready,
            )
        )
        preflight_digest = self.compute_preflight_digest(
            product_id=product_id,
            current_context_digest=context.context_digest,
            calculated_recommendation_digest=calculated_recommendation_digest,
            current_marketing_strategy_id=(
                strategy.id if strategy is not None else None
            ),
            current_copy_matrix_id=(
                copy_matrix.id if copy_matrix is not None else None
            ),
            current_video_project_id=(
                video_project.id if video_project is not None else None
            ),
            request=data,
            target_platforms=target_platforms,
        )
        return V2CopyPreflightRead(
            product_id=product_id,
            source_context_digest=data.source_context_digest,
            source_recommendation_digest=data.recommendation_digest,
            source_marketing_strategy_id=data.source_marketing_strategy_id,
            source_copy_matrix_id=data.source_copy_matrix_id,
            source_video_project_id=data.source_video_project_id,
            target_platforms=target_platforms,
            expected_copy_count=len(target_platforms),
            input_ready=input_ready,
            provider_configured=provider_configured,
            copy_execution_enabled=self.settings.enable_copy_execution,
            v2_copy_execution_enabled=self.settings.enable_v2_copy_execution,
            contract_ready=contract_ready,
            ready_for_execution=ready_for_execution,
            missing_requirements=list(dict.fromkeys(missing)),
            preflight_digest=preflight_digest,
            cost_notice=V2_COPY_COST_NOTICE,
            association_notice=V2_COPY_ASSOCIATION_NOTICE,
        )

    @staticmethod
    def compute_preflight_digest(
        *,
        product_id: int,
        current_context_digest: str,
        calculated_recommendation_digest: str,
        current_marketing_strategy_id: int | None,
        current_copy_matrix_id: int | None,
        current_video_project_id: int | None,
        request: V2CopySourceRequest,
        target_platforms: list[str],
    ) -> str:
        payload = {
            "contract_version": V2_COPY_CONTRACT_VERSION,
            "product_id": product_id,
            "current_context_digest": current_context_digest,
            "calculated_recommendation_digest": (
                calculated_recommendation_digest
            ),
            "current_source_ids": {
                "marketing_strategy_id": current_marketing_strategy_id,
                "copy_matrix_id": current_copy_matrix_id,
                "video_project_id": current_video_project_id,
            },
            "requested_source": {
                "context_digest": request.source_context_digest,
                "recommendation_digest": request.recommendation_digest,
                "marketing_strategy_id": request.source_marketing_strategy_id,
                "copy_matrix_id": request.source_copy_matrix_id,
                "video_project_id": request.source_video_project_id,
            },
            "target_platforms": target_platforms,
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _provider_configured(self) -> bool:
        secret = self.settings.dashscope_api_key
        return bool(secret and secret.get_secret_value().strip())

    @staticmethod
    def _same_chain(
        data: V2CopySourceRequest,
        strategy: MarketingStrategy | None,
        copy_matrix: CopyMatrix | None,
        video_project: VideoProject | None,
        product_id: int,
    ) -> bool:
        return bool(
            strategy is not None
            and copy_matrix is not None
            and video_project is not None
            and strategy.id == data.source_marketing_strategy_id
            and copy_matrix.id == data.source_copy_matrix_id
            and video_project.id == data.source_video_project_id
            and strategy.product_id == product_id
            and copy_matrix.product_id == product_id
            and video_project.product_id == product_id
            and copy_matrix.marketing_strategy_id == strategy.id
            and video_project.marketing_strategy_id == strategy.id
            and video_project.copy_matrix_id == copy_matrix.id
        )

    @staticmethod
    def _target_platforms_valid(
        target_platforms: list[str], copy_matrix: CopyMatrix | None
    ) -> bool:
        if not target_platforms or len(target_platforms) != len(
            {item.casefold() for item in target_platforms}
        ):
            return False
        if copy_matrix is None:
            return False
        source_platforms = {
            str(item.get("platform", "")).strip().casefold()
            for item in (copy_matrix.copies or [])
            if isinstance(item, dict)
        }
        return all(
            platform.casefold() in source_platforms
            for platform in target_platforms
        )

    @staticmethod
    def _product_ready(product: Product) -> bool:
        def valid_text(value: object) -> bool:
            return isinstance(value, str) and bool(value.strip())

        selling_points = product.selling_points
        return (
            valid_text(product.name)
            and valid_text(product.category)
            and valid_text(product.description)
            and isinstance(selling_points, list)
            and bool(selling_points)
            and all(valid_text(item) for item in selling_points)
        )
