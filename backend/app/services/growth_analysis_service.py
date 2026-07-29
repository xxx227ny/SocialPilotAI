import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import CopyMatrix, MarketingStrategy, VideoProject
from app.providers import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderModelError,
    ProviderQuotaError,
    TextGenerationProvider,
)
from app.schemas.growth import (
    GrowthAnalysisResponse,
    GrowthRecommendationConstraints,
)
from app.services.feedback_context_service import FeedbackContextService
from app.services.growth_recommendation_preflight import (
    extract_supported_growth_platforms,
    resolve_growth_reference_platforms,
    supported_growth_platform,
)


class GrowthAnalysisService:
    """Generate one non-persistent recommendation for one exact Context."""

    def __init__(
        self,
        session: Session,
        provider: TextGenerationProvider,
        settings: Settings,
    ) -> None:
        self.settings = settings
        self.feedback_service = FeedbackContextService(session)
        self.provider = provider

    def analyze(
        self,
        product_id: int,
        expected_context_digest: str,
    ) -> GrowthAnalysisResponse:
        self._require_execution_enabled()
        self._require_provider_configured()
        context, strategy, copy_matrix, video_project = (
            self.feedback_service.get_with_validated_chain(product_id)
        )
        if (
            not context.context_ready
            or strategy is None
            or copy_matrix is None
            or video_project is None
        ):
            raise AppError(
                "FeedbackContext is not ready; read Context and Preflight again",
                status_code=409,
            )
        if context.context_digest != expected_context_digest:
            raise AppError(
                "FeedbackContext changed; read Context and Preflight again",
                status_code=409,
            )
        try:
            copy_supported, expected_video_platform = (
                resolve_growth_reference_platforms(copy_matrix, video_project)
            )
        except ValueError as exc:
            raise AppError(
                "FeedbackContext reference platforms changed; "
                "read Context and Preflight again",
                status_code=409,
            ) from exc
        observation_supported = set(
            extract_supported_growth_platforms(context.platforms)
        )

        try:
            raw_result = self.provider.generate(
                self._build_prompt(
                    context=context.model_dump(mode="json"),
                    strategy=strategy,
                    copy_matrix=copy_matrix,
                    video_project=video_project,
                    allowed_observation_platforms=observation_supported,
                    allowed_copy_constraint_platforms=copy_supported,
                    required_video_constraint_platform=expected_video_platform,
                )
            )
        except ProviderAuthenticationError as exc:
            raise AppError("Qwen authentication failed", status_code=502) from exc
        except ProviderConnectionError as exc:
            raise AppError("Qwen service is unavailable", status_code=503) from exc
        except ProviderQuotaError as exc:
            raise AppError(
                "Qwen quota or rate limit prevents execution",
                status_code=503,
            ) from exc
        except ProviderModelError as exc:
            raise AppError("Qwen generation failed", status_code=502) from exc

        try:
            recommendation = GrowthRecommendationConstraints.model_validate_json(
                raw_result
            )
            self._validate_platform_contract(
                recommendation,
                observation_supported=observation_supported,
                copy_supported=copy_supported,
                expected_video_platform=expected_video_platform,
            )
        except (ValidationError, ValueError) as exc:
            raise AppError(
                "Qwen returned invalid recommendation data", status_code=502
            ) from exc

        return GrowthAnalysisResponse(
            product_id=product_id,
            source_context_digest=context.context_digest,
            source_marketing_strategy_id=strategy.id,
            source_copy_matrix_id=copy_matrix.id,
            source_video_project_id=video_project.id,
            recommendation=recommendation,
        )

    def _require_execution_enabled(self) -> None:
        if not self.settings.enable_growth_execution:
            raise AppError(
                "Growth analysis execution is disabled by the server",
                status_code=503,
            )

    def _require_provider_configured(self) -> None:
        secret = self.settings.dashscope_api_key
        if secret is None or not secret.get_secret_value().strip():
            raise AppError("Qwen provider is not configured", status_code=503)

    @staticmethod
    def _validate_platform_contract(
        recommendation: GrowthRecommendationConstraints,
        *,
        observation_supported: set[str],
        copy_supported: set[str],
        expected_video_platform: str,
    ) -> None:
        output_copy_platforms = {
            item.platform for item in recommendation.copy_constraints
        }
        if not output_copy_platforms.issubset(copy_supported):
            raise ValueError(
                "copy constraints must use exact CopyMatrix platforms"
            )
        for observation in recommendation.observations:
            if (
                observation.scope == "platform"
                and observation.platform not in observation_supported
            ):
                raise ValueError(
                    "platform observation has no matching Campaign metrics"
                )
        if recommendation.video_constraint.platform != expected_video_platform:
            raise ValueError(
                "video constraint must match exact VideoProject platform"
            )

    @staticmethod
    def _build_prompt(
        *,
        context: dict[str, object],
        strategy: MarketingStrategy,
        copy_matrix: CopyMatrix,
        video_project: VideoProject,
        allowed_observation_platforms: set[str],
        allowed_copy_constraint_platforms: set[str],
        required_video_constraint_platform: str,
    ) -> str:
        platform_metrics = []
        for item in context["platform_metrics"]:
            if not isinstance(item, dict):
                continue
            platform = supported_growth_platform(str(item.get("platform", "")))
            if (
                platform is None
                or platform not in allowed_observation_platforms
            ):
                continue
            platform_metrics.append({**item, "platform": platform})
        safe_context = {
            "overall_metrics": context["overall_metrics"],
            "platform_metrics": platform_metrics,
            "date_from": context["date_from"],
            "date_to": context["date_to"],
            "campaign_count": context["campaign_count"],
            "campaign_association_scope": "product_only",
        }
        reference_content = {
            "marketing_strategy": {
                "positioning": strategy.positioning,
                "audience_insights": strategy.audience_insights,
                "angles": strategy.angles,
                "risks": strategy.risks,
                "evidence": strategy.evidence,
            },
            "copy_matrix": {"copies": copy_matrix.copies},
            "video_project": {
                "platform": video_project.platform,
                "title": video_project.title,
                "concept": video_project.concept,
                "duration_seconds": video_project.duration_seconds,
                "aspect_ratio": video_project.aspect_ratio,
                "scenes": video_project.scenes,
                "cta": video_project.cta,
            },
        }
        payload = {
            "allowed_observation_platforms": sorted(
                allowed_observation_platforms
            ),
            "allowed_copy_constraint_platforms": sorted(
                allowed_copy_constraint_platforms
            ),
            "required_video_constraint_platform": (
                required_video_constraint_platform
            ),
            "calculated_feedback_context": safe_context,
            "validated_reference_content": reference_content,
            "required_output_schema": (
                GrowthRecommendationConstraints.model_json_schema()
            ),
        }
        return (
            "Return one strict JSON Recommendation object only. Use the "
            "Backend-calculated metrics as given; never recalculate CTR, "
            "conversion_rate, CPA, or ROAS. Campaign metrics are Product-level "
            "performance and do not prove that the referenced CopyMatrix, "
            "VideoProject, Artifact, or creative caused the result. Express only "
            "test hypotheses and constraints for a possible later generation "
            "stage. Do not generate Copy or Video, modify a budget, publish an "
            "ad, Submit, Refresh, or claim any automatic action. Do not return "
            "Product IDs, Context digests, content-chain IDs, permissions, "
            "execution fields, Provider data, or extra fields. Context:\n"
            f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )
