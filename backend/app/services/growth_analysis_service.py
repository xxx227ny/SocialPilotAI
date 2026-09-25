import json
import math

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import CopyMatrix, MarketingStrategy, Product, VideoProject
from app.providers import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderError,
    ProviderModelError,
    ProviderQuotaError,
    TextGenerationProvider,
)
from app.providers.live_configuration import (
    get_provider_failure_metadata,
    provider_failure_metadata,
    provider_public_http_status,
    public_provider_failure,
    qwen_provider_configured,
    safe_error_message,
)
from app.repositories.product import ProductRepository
from app.schemas.campaign import CampaignMetricsSchema
from app.schemas.growth import (
    FeedbackContextRead,
    GrowthAnalysisResponse,
    GrowthCopyConstraint,
    GrowthObservation,
    GrowthRecommendationConstraints,
    GrowthRecommendationDraft,
    GrowthRecommendationDraftObservation,
    GrowthVideoConstraint,
    compute_recommendation_digest,
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
        self.product_repository = ProductRepository(session)
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
        product = self.product_repository.get(product_id)
        if (
            not context.context_ready
            or product is None
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
        product_facts = self._product_facts(product)

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
                    product_facts=product_facts,
                )
            )
        except ProviderError as exc:
            metadata = get_provider_failure_metadata(exc)
            if metadata is not None:
                raise AppError(
                    safe_error_message(metadata),
                    provider_public_http_status(metadata),
                    provider_failure=public_provider_failure(metadata),
                ) from exc
            if isinstance(exc, ProviderAuthenticationError):
                raise AppError("Qwen authentication failed", status_code=502) from exc
            if isinstance(exc, ProviderConnectionError):
                raise AppError("Qwen service is unavailable", status_code=503) from exc
            if isinstance(exc, ProviderQuotaError):
                raise AppError(
                    "Qwen quota or rate limit prevents execution",
                    status_code=503,
                ) from exc
            if isinstance(exc, ProviderModelError):
                raise AppError("Qwen generation failed", status_code=502) from exc
            raise

        try:
            draft = GrowthRecommendationDraft.model_validate_json(raw_result)
            self._validate_draft_contract(
                draft,
                context=context,
                observation_supported=observation_supported,
                copy_supported=copy_supported,
                expected_video_platform=expected_video_platform,
                product_facts=product_facts,
            )
            recommendation = self._materialize_recommendation(
                draft,
                context=context,
                product_facts=product_facts,
            )
        except (ValidationError, ValueError) as exc:
            metadata = provider_failure_metadata(
                provider="qwen",
                phase="schema",
                provider_code="invalid_provider_output",
                uncertain=False,
                potentially_billable=True,
            )
            raise AppError(
                "Qwen returned invalid recommendation data",
                status_code=provider_public_http_status(metadata),
                provider_failure=public_provider_failure(metadata),
            ) from exc

        recommendation_digest = compute_recommendation_digest(
            product_id=product_id,
            source_context_digest=context.context_digest,
            source_marketing_strategy_id=strategy.id,
            source_copy_matrix_id=copy_matrix.id,
            source_video_project_id=video_project.id,
            recommendation=recommendation,
        )
        return GrowthAnalysisResponse(
            product_id=product_id,
            source_context_digest=context.context_digest,
            source_marketing_strategy_id=strategy.id,
            source_copy_matrix_id=copy_matrix.id,
            source_video_project_id=video_project.id,
            recommendation=recommendation,
            recommendation_digest=recommendation_digest,
        )

    def _require_execution_enabled(self) -> None:
        if not self.settings.enable_growth_execution:
            raise AppError(
                "Growth analysis execution is disabled by the server",
                status_code=503,
            )

    def _require_provider_configured(self) -> None:
        if not qwen_provider_configured(self.settings):
            raise AppError("Qwen provider is not configured", status_code=503)

    @classmethod
    def _validate_draft_contract(
        cls,
        draft: GrowthRecommendationDraft,
        *,
        context: FeedbackContextRead,
        observation_supported: set[str],
        copy_supported: set[str],
        expected_video_platform: str,
        product_facts: dict[str, str],
    ) -> None:
        output_copy_platforms = {item.platform for item in draft.copy_constraints}
        if output_copy_platforms != copy_supported:
            raise ValueError(
                "copy constraints must cover the exact CopyMatrix platforms"
            )
        for item in draft.copy_constraints:
            cls._validate_fact_ids(item.product_fact_ids, product_facts)
        if draft.video_constraint.platform != expected_video_platform:
            raise ValueError("video constraint must match exact VideoProject platform")
        cls._validate_fact_ids(
            draft.video_constraint.product_fact_ids,
            product_facts,
        )

        for observation in draft.observations:
            if (
                observation.scope == "platform"
                and observation.platform not in observation_supported
            ):
                raise ValueError(
                    "platform observation has no matching Campaign metrics"
                )
            expected = cls._metric_value(
                context,
                scope=observation.scope,
                platform=observation.platform,
                metric=observation.metric,
            )
            if not cls._same_metric_value(observation.observed_value, expected):
                raise ValueError(
                    "observation value does not match backend-calculated metrics"
                )
        cls._validate_priority_coverage(draft, context)

    @staticmethod
    def _validate_fact_ids(
        fact_ids: list[str],
        product_facts: dict[str, str],
    ) -> None:
        if any(fact_id not in product_facts for fact_id in fact_ids):
            raise ValueError("recommendation references an unknown product fact")

    @classmethod
    def _validate_priority_coverage(
        cls,
        draft: GrowthRecommendationDraft,
        context: FeedbackContextRead,
    ) -> None:
        metrics = cls._platform_metric_map(context)
        roas = [
            (platform, item.roas)
            for platform, item in metrics.items()
            if item.roas is not None
        ]
        if roas:
            lowest = min(value for _, value in roas)
            highest = max(value for _, value in roas)
            if not math.isclose(lowest, highest, rel_tol=1e-9, abs_tol=1e-9):
                worst_platforms = {
                    platform
                    for platform, value in roas
                    if math.isclose(value, lowest, rel_tol=1e-9, abs_tol=1e-9)
                }
                best_platforms = {
                    platform
                    for platform, value in roas
                    if math.isclose(value, highest, rel_tol=1e-9, abs_tol=1e-9)
                }
                if not any(
                    item.scope == "platform"
                    and item.platform in worst_platforms
                    and item.metric == "roas"
                    and item.direction in {"improve", "investigate"}
                    for item in draft.observations
                ):
                    raise ValueError("lowest ROAS platform must be prioritized")
                if not any(
                    item.scope == "platform"
                    and item.platform in best_platforms
                    and item.metric == "roas"
                    and item.direction == "protect"
                    for item in draft.observations
                ):
                    raise ValueError("highest ROAS platform must be protected")

        cpa = [
            (platform, item.cpa)
            for platform, item in metrics.items()
            if item.cpa is not None
        ]
        if cpa:
            lowest = min(value for _, value in cpa)
            highest = max(value for _, value in cpa)
            if not math.isclose(lowest, highest, rel_tol=1e-9, abs_tol=1e-9):
                worst_platforms = {
                    platform
                    for platform, value in cpa
                    if math.isclose(value, highest, rel_tol=1e-9, abs_tol=1e-9)
                }
                if not any(
                    item.scope == "platform"
                    and item.platform in worst_platforms
                    and item.metric == "cpa"
                    and item.direction == "investigate"
                    for item in draft.observations
                ):
                    raise ValueError("highest CPA platform must be investigated")

    @classmethod
    def _materialize_recommendation(
        cls,
        draft: GrowthRecommendationDraft,
        *,
        context: FeedbackContextRead,
        product_facts: dict[str, str],
    ) -> GrowthRecommendationConstraints:
        observations = [
            GrowthObservation(
                scope=item.scope,
                platform=item.platform,
                metric=item.metric,
                direction=item.direction,
                hypothesis=cls._observation_text(item, context),
            )
            for item in draft.observations
        ]
        copy_constraints = [
            GrowthCopyConstraint(
                platform=item.platform,
                hook_direction=item.hook_direction,
                message_angle=item.message_angle,
                cta_direction=item.cta_direction,
                must_preserve=[
                    product_facts[fact_id] for fact_id in item.product_fact_ids
                ],
                must_avoid=list(item.risk_controls),
            )
            for item in draft.copy_constraints
        ]
        video = draft.video_constraint
        return GrowthRecommendationConstraints(
            summary=cls._summary_text(context),
            observations=observations,
            copy_constraints=copy_constraints,
            video_constraint=GrowthVideoConstraint(
                platform=video.platform,
                opening_hook_direction=video.opening_hook_direction,
                visual_focus=video.visual_focus,
                pacing_direction=video.pacing_direction,
                cta_direction=video.cta_direction,
                must_preserve=[
                    product_facts[fact_id] for fact_id in video.product_fact_ids
                ],
                must_avoid=list(video.risk_controls),
            ),
            budget_guidance=cls._budget_guidance_text(
                draft.budget_strategy,
                context,
            ),
        )

    @classmethod
    def _observation_text(
        cls,
        observation: GrowthRecommendationDraftObservation,
        context: FeedbackContextRead,
    ) -> str:
        scope = observation.scope
        platform = observation.platform
        metric = observation.metric
        direction = observation.direction
        value = cls._metric_value(
            context,
            scope=scope,
            platform=platform,
            metric=metric,
        )
        subject = "总体" if scope == "overall" else str(platform)
        metric_labels = {
            "ctr": "点击率",
            "conversion_rate": "转化率",
            "cpa": "单次转化成本",
            "roas": "广告支出回报率",
        }
        direction_labels = {
            "improve": "进行优化",
            "test": "开展受控测试",
            "protect": "保护当前表现",
            "investigate": "优先排查原因",
        }
        return (
            f"{subject}的{metric_labels[metric]}为{cls._format_metric(metric, value)}；"
            f"建议{direction_labels[direction]}。该结论仅基于商品级广告数据，"
            "不代表当前文案或视频直接造成该结果。"
        )

    @classmethod
    def _summary_text(cls, context: FeedbackContextRead) -> str:
        metrics = cls._platform_metric_map(context)
        roas = [
            (platform, item.roas)
            for platform, item in metrics.items()
            if item.roas is not None
        ]
        if len(roas) < 2:
            return (
                "当前数据不足以比较多个平台；建议保持人工复核，并通过受控测试"
                "积累更多商品级广告数据。"
            )
        worst_platform, worst_roas = min(roas, key=lambda item: item[1])
        best_platform, best_roas = max(roas, key=lambda item: item[1])
        worst_cpa = metrics[worst_platform].cpa
        return (
            f"优先排查{worst_platform}（广告支出回报率"
            f"{cls._format_metric('roas', worst_roas)}、单次转化成本"
            f"{cls._format_metric('cpa', worst_cpa)}），同时保护"
            f"{best_platform}（广告支出回报率"
            f"{cls._format_metric('roas', best_roas)}）的有效投放。"
            "所有建议仅基于商品级广告数据，仍需通过受控测试验证。"
        )

    @classmethod
    def _budget_guidance_text(
        cls,
        strategy: str,
        context: FeedbackContextRead,
    ) -> str:
        metrics = cls._platform_metric_map(context)
        roas = [
            (platform, item.roas)
            for platform, item in metrics.items()
            if item.roas is not None
        ]
        if strategy == "数据不足时转为人工复核" or len(roas) < 2:
            return (
                "暂不调整预算，先由人工复核数据完整性；当前不会修改任何外部广告账户。"
            )
        worst_platform, _ = min(roas, key=lambda item: item[1])
        best_platform, _ = max(roas, key=lambda item: item[1])
        if strategy == "保持预算并进行受控测试":
            return (
                f"保持总预算不变，先对{worst_platform}进行小范围受控测试，并继续"
                f"观察{best_platform}；当前不会修改任何外部广告账户。"
            )
        return (
            f"仅在内部沙箱中模拟降低{worst_platform}占比并保护{best_platform}；"
            "实际幅度由确定性预算模块计算，当前不会修改任何外部广告账户。"
        )

    @classmethod
    def _metric_value(
        cls,
        context: FeedbackContextRead,
        *,
        scope: str,
        platform: str | None,
        metric: str,
    ) -> float | None:
        if scope == "overall":
            metrics = context.overall_metrics
        else:
            metrics = cls._platform_metric_map(context).get(str(platform))
        if metrics is None:
            raise ValueError("observation metric scope is unavailable")
        value = getattr(metrics, metric)
        return None if value is None else float(value)

    @staticmethod
    def _same_metric_value(
        actual: float | None,
        expected: float | None,
    ) -> bool:
        if actual is None or expected is None:
            return actual is expected
        return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)

    @staticmethod
    def _format_metric(metric: str, value: float | None) -> str:
        if value is None:
            return "暂无可计算值"
        if metric in {"ctr", "conversion_rate"}:
            return f"{value * 100:.2f}%"
        if metric == "cpa":
            return f"{value:.2f} 美元"
        return f"{value:.2f} 倍"

    @staticmethod
    def _platform_metric_map(
        context: FeedbackContextRead,
    ) -> dict[str, CampaignMetricsSchema]:
        result: dict[str, CampaignMetricsSchema] = {}
        for item in context.platform_metrics:
            platform = supported_growth_platform(item.platform)
            if platform is not None:
                result[platform] = item.metrics
        return result

    @staticmethod
    def _product_facts(product: Product) -> dict[str, str]:
        facts: dict[str, str] = {}
        seen: set[str] = set()
        for raw in product.selling_points:
            fact = str(raw).strip()
            key = fact.casefold()
            if not fact or key in seen:
                continue
            seen.add(key)
            facts[f"fact_{len(facts) + 1}"] = fact
        if not facts:
            raise ValueError("product has no verified selling points")
        return facts

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
        product_facts: dict[str, str],
    ) -> str:
        platform_metrics = []
        for item in context["platform_metrics"]:
            if not isinstance(item, dict):
                continue
            platform = supported_growth_platform(str(item.get("platform", "")))
            if platform is None or platform not in allowed_observation_platforms:
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
            "allowed_observation_platforms": sorted(allowed_observation_platforms),
            "allowed_copy_constraint_platforms": sorted(
                allowed_copy_constraint_platforms
            ),
            "required_video_constraint_platform": (required_video_constraint_platform),
            "verified_product_facts": [
                {"id": fact_id, "text": text} for fact_id, text in product_facts.items()
            ],
            "calculated_feedback_context": safe_context,
            "validated_reference_content": reference_content,
            "required_output_schema": (GrowthRecommendationDraft.model_json_schema()),
        }
        return (
            "只返回一个严格符合 required_output_schema 的 JSON 对象。所有策略"
            "字段只能选择 Schema 中给出的中文枚举值，不得输出自由文本。每条"
            "观察必须原样复制 Backend 计算的对应 observed_value，禁止重算、"
            "四舍五入或把总体指标归到某个平台。copy_constraints 必须完整覆盖"
            " allowed_copy_constraint_platforms；video_constraint 必须使用"
            " required_video_constraint_platform。商品卖点只能通过"
            " verified_product_facts 中的 fact_N 编号引用，禁止改写、翻译或新增"
            "卖点。必须优先覆盖最低 ROAS、最高 CPA，并保护最高 ROAS；若数值"
            "并列则无需虚构差异。广告指标仅代表商品级表现，不能证明当前文案、"
            "视频或素材造成结果。不得生成文案或视频、修改预算、发布广告、执行"
            "自动操作，也不得返回商品编号、摘要、内容链编号、权限、Provider"
            " 数据或额外字段。上下文：\n"
            f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )
