import hashlib
import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CopyMatrix, MarketingStrategy, VideoProject
from app.providers.live_configuration import (
    qwen_missing_requirements,
    qwen_provider_configured,
)
from app.repositories.copy import CopyMatrixRepository
from app.repositories.product import ProductRepository
from app.schemas.copy import V2PlatformCopySchema
from app.schemas.growth import compute_recommendation_digest
from app.schemas.video import (
    V2_VIDEO_PROJECT_CONTRACT_VERSION,
    V2VideoProjectPreflightRead,
    V2VideoProjectSourceRequest,
    VideoPlanSchema,
)
from app.services.feedback_context_service import FeedbackContextService
from app.services.v2_copy_preflight import V2CopyPreflightService

V2_VIDEO_PROJECT_COST_NOTICE = (
    "Generating a V2 VideoProject calls Qwen and may incur provider charges. "
    "It does not call Wanx or render media."
)
V2_VIDEO_PROJECT_ASSOCIATION_NOTICE = (
    "The new VideoProject persistently references Product, the exact source "
    "MarketingStrategy, and the exact candidate CopyMatrix. Recommendation, "
    "FeedbackContext, candidate-Copy parentage, and old-to-new VideoProject "
    "parentage are not persisted."
)


class V2VideoProjectPreflightService:
    """Validate one candidate-Copy-bound VideoProject operation read-only."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.settings = settings
        self.feedback_service = FeedbackContextService(session)
        self.product_repository = ProductRepository(session)
        self.copy_repository = CopyMatrixRepository(session)

    def run(
        self, product_id: int, data: V2VideoProjectSourceRequest
    ) -> V2VideoProjectPreflightRead:
        context, strategy, source_copy, source_video = (
            self.feedback_service.get_with_validated_chain(product_id)
        )
        product = self.product_repository.get(product_id)
        assert product is not None
        candidate_copy = self.copy_repository.get(data.candidate_copy_matrix_id)
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
        if not self._same_source_chain(
            data, strategy, source_copy, source_video, product_id
        ):
            missing.append("source_content_chain_mismatch")
        source_plan = self._validated_source_plan(source_video)
        if source_video is not None and source_plan is None:
            missing.append("source_video_project_schema")
        if not V2CopyPreflightService._product_ready(product):
            missing.append("product_input")
        if not self._candidate_copy_valid(
            candidate_copy,
            product_id=product_id,
            strategy_id=data.source_marketing_strategy_id,
            source_copy_id=data.source_copy_matrix_id,
        ):
            missing.append("candidate_copy_matrix_mismatch")

        platform = source_plan.platform if source_plan is not None else ""
        if (
            source_plan is None
            or data.recommendation.video_constraint.platform != platform
        ):
            missing.append("recommendation_video_platform")
        if not self._candidate_has_platform(candidate_copy, platform):
            missing.append("candidate_copy_platform")

        provider_configured = self._provider_configured()
        if not provider_configured:
            missing.append("provider_configuration")
            missing.extend(qwen_missing_requirements(self.settings))
        execution_enabled = self.settings.enable_v2_video_project_execution
        if not execution_enabled:
            missing.append("v2_video_project_execution")

        input_requirements = {
            "campaign_data",
            "video_project",
            "marketing_strategy",
            "copy_matrix",
            "exact_content_chain",
            "stale_context_digest",
            "recommendation_digest_mismatch",
            "source_content_chain_mismatch",
            "source_video_project_schema",
            "product_input",
            "candidate_copy_matrix_mismatch",
            "recommendation_video_platform",
            "candidate_copy_platform",
        }
        input_ready = not any(item in input_requirements for item in missing)
        duration_seconds = (
            source_plan.duration_seconds if source_plan is not None else 0
        )
        aspect_ratio = (
            source_plan.aspect_ratio if source_plan is not None else ""
        )
        preflight_digest = self.compute_preflight_digest(
            product_id=product_id,
            current_context_digest=context.context_digest,
            calculated_recommendation_digest=calculated_recommendation_digest,
            request=data,
            current_strategy_id=strategy.id if strategy else None,
            current_source_copy_id=source_copy.id if source_copy else None,
            current_source_video_id=source_video.id if source_video else None,
            source_video=source_video,
            source_video_schema_valid=source_plan is not None,
            candidate_copy=candidate_copy,
            platform=platform,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
        )
        return V2VideoProjectPreflightRead(
            product_id=product_id,
            source_context_digest=data.source_context_digest,
            source_recommendation_digest=data.recommendation_digest,
            source_marketing_strategy_id=data.source_marketing_strategy_id,
            source_copy_matrix_id=data.source_copy_matrix_id,
            source_video_project_id=data.source_video_project_id,
            candidate_copy_matrix_id=data.candidate_copy_matrix_id,
            platform=platform,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            input_ready=input_ready,
            provider_configured=provider_configured,
            v2_video_project_execution_enabled=execution_enabled,
            contract_ready=True,
            ready_for_execution=(
                input_ready and provider_configured and execution_enabled
            ),
            missing_requirements=list(dict.fromkeys(missing)),
            preflight_digest=preflight_digest,
            cost_notice=V2_VIDEO_PROJECT_COST_NOTICE,
            association_notice=V2_VIDEO_PROJECT_ASSOCIATION_NOTICE,
        )

    @staticmethod
    def compute_preflight_digest(
        *,
        product_id: int,
        current_context_digest: str,
        calculated_recommendation_digest: str,
        request: V2VideoProjectSourceRequest,
        current_strategy_id: int | None,
        current_source_copy_id: int | None,
        current_source_video_id: int | None,
        source_video: VideoProject | None,
        source_video_schema_valid: bool,
        candidate_copy: CopyMatrix | None,
        platform: str,
        duration_seconds: int,
        aspect_ratio: str,
    ) -> str:
        candidate_content = V2VideoProjectPreflightService._normalize_digest_value(
            candidate_copy.copies if candidate_copy else []
        )
        candidate_summary = hashlib.sha256(
            json.dumps(
                candidate_content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        source_video_content = (
            V2VideoProjectPreflightService._normalize_digest_value(
                {
                    "title": source_video.title,
                    "concept": source_video.concept,
                    "platform": source_video.platform,
                    "duration_seconds": source_video.duration_seconds,
                    "aspect_ratio": source_video.aspect_ratio,
                    "scenes": source_video.scenes,
                    "cta": source_video.cta,
                }
            )
            if source_video is not None
            else None
        )
        source_video_summary = hashlib.sha256(
            json.dumps(
                source_video_content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        payload = {
            "contract_version": V2_VIDEO_PROJECT_CONTRACT_VERSION,
            "product_id": product_id,
            "current_context_digest": current_context_digest,
            "calculated_recommendation_digest": (
                calculated_recommendation_digest
            ),
            "current_source_ids": {
                "marketing_strategy_id": current_strategy_id,
                "copy_matrix_id": current_source_copy_id,
                "video_project_id": current_source_video_id,
            },
            "requested_source": {
                "context_digest": request.source_context_digest,
                "recommendation_digest": request.recommendation_digest,
                "marketing_strategy_id": request.source_marketing_strategy_id,
                "copy_matrix_id": request.source_copy_matrix_id,
                "video_project_id": request.source_video_project_id,
            },
            "candidate_copy_matrix_id": request.candidate_copy_matrix_id,
            "candidate_copy_identity": {
                "id": candidate_copy.id if candidate_copy else None,
                "product_id": (
                    candidate_copy.product_id if candidate_copy else None
                ),
                "marketing_strategy_id": (
                    candidate_copy.marketing_strategy_id
                    if candidate_copy
                    else None
                ),
            },
            "candidate_copy_content_digest": candidate_summary,
            "source_video_project_schema_valid": source_video_schema_valid,
            "source_video_project_content_digest": source_video_summary,
            "platform": platform,
            "duration_seconds": duration_seconds,
            "aspect_ratio": aspect_ratio,
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _provider_configured(self) -> bool:
        return qwen_provider_configured(self.settings)

    @staticmethod
    def _same_source_chain(
        data: V2VideoProjectSourceRequest,
        strategy: MarketingStrategy | None,
        source_copy: CopyMatrix | None,
        source_video: VideoProject | None,
        product_id: int,
    ) -> bool:
        return bool(
            strategy is not None
            and source_copy is not None
            and source_video is not None
            and strategy.id == data.source_marketing_strategy_id
            and source_copy.id == data.source_copy_matrix_id
            and source_video.id == data.source_video_project_id
            and strategy.product_id == product_id
            and source_copy.product_id == product_id
            and source_video.product_id == product_id
            and source_copy.marketing_strategy_id == strategy.id
            and source_video.marketing_strategy_id == strategy.id
            and source_video.copy_matrix_id == source_copy.id
        )

    @staticmethod
    def _candidate_copy_valid(
        candidate: CopyMatrix | None,
        *,
        product_id: int,
        strategy_id: int,
        source_copy_id: int,
    ) -> bool:
        return bool(
            candidate is not None
            and candidate.id != source_copy_id
            and candidate.product_id == product_id
            and candidate.marketing_strategy_id == strategy_id
        )

    @staticmethod
    def _validated_source_plan(
        source_video: VideoProject | None,
    ) -> VideoPlanSchema | None:
        if source_video is None:
            return None
        try:
            plan = VideoPlanSchema.model_validate(
                {
                    "title": source_video.title,
                    "concept": source_video.concept,
                    "platform": source_video.platform,
                    "duration_seconds": source_video.duration_seconds,
                    "aspect_ratio": source_video.aspect_ratio,
                    "scenes": source_video.scenes,
                    "cta": source_video.cta,
                }
            )
        except (AttributeError, TypeError, ValidationError, ValueError):
            return None
        sequences = [scene.sequence for scene in plan.scenes]
        if sequences != list(range(1, len(plan.scenes) + 1)):
            return None
        return plan

    @staticmethod
    def _candidate_has_platform(
        candidate: CopyMatrix | None, platform: str
    ) -> bool:
        if candidate is None or not platform:
            return False
        matching = [
            item
            for item in (candidate.copies or [])
            if isinstance(item, dict)
            and str(item.get("platform", "")).strip().casefold()
            == platform.casefold()
        ]
        if len(matching) != 1:
            return False
        try:
            parsed = V2PlatformCopySchema.model_validate(matching[0])
        except ValidationError:
            return False
        return parsed.platform.casefold() == platform.casefold()

    @staticmethod
    def _normalize_digest_value(value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return [
                V2VideoProjectPreflightService._normalize_digest_value(item)
                for item in value
            ]
        if isinstance(value, dict):
            return {
                str(key).strip(): (
                    V2VideoProjectPreflightService._normalize_digest_value(item)
                )
                for key, item in value.items()
            }
        return value
