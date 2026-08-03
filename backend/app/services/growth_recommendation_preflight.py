from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CopyMatrix, VideoProject
from app.providers.live_configuration import (
    qwen_missing_requirements,
    qwen_provider_configured,
)
from app.schemas.growth import (
    GrowthRecommendationPreflightRead,
    normalize_growth_platform,
)
from app.services.feedback_context_service import FeedbackContextService

GROWTH_PROVIDER_LABEL = "Alibaba Cloud Bailian Qwen"
GROWTH_COST_NOTICE = (
    "执行Recommendation将调用阿里云百炼Qwen，并可能产生费用；"
    "具体消耗由模型、输入输出长度和平台计费决定。"
)


def supported_growth_platform(value: str) -> str | None:
    """Return a controlled platform, ignoring unrelated Campaign channels."""
    try:
        return normalize_growth_platform(value)
    except ValueError:
        return None


def extract_supported_growth_platforms(values: list[str]) -> list[str]:
    """Extract stable, unique platforms that may scope an observation."""
    platforms: list[str] = []
    seen: set[str] = set()
    for value in values:
        platform = supported_growth_platform(value)
        if platform is None or platform.casefold() in seen:
            continue
        seen.add(platform.casefold())
        platforms.append(platform)
    return platforms


def resolve_growth_reference_platforms(
    copy_matrix: CopyMatrix | None,
    video_project: VideoProject | None,
) -> tuple[set[str], str]:
    """Return validated platforms for the exact reference chain."""
    if copy_matrix is None or video_project is None:
        raise ValueError("exact reference chain is incomplete")
    copies = copy_matrix.copies or []
    if not copies or any(not isinstance(item, dict) for item in copies):
        raise ValueError("CopyMatrix platforms are incomplete")
    copy_platforms = [
        normalize_growth_platform(str(item.get("platform", "")))
        for item in copies
    ]
    normalized_copy_platforms = {
        item.casefold() for item in copy_platforms
    }
    if len(normalized_copy_platforms) != len(copy_platforms):
        raise ValueError("CopyMatrix platforms are duplicated")
    return set(copy_platforms), normalize_growth_platform(
        video_project.platform
    )


class GrowthRecommendationPreflightService:
    """Evaluate the local Recommendation contract without resolving a Provider."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.settings = settings
        self.feedback_service = FeedbackContextService(session)

    def run(self, product_id: int) -> GrowthRecommendationPreflightRead:
        context, _, copy_matrix, video_project = (
            self.feedback_service.get_with_validated_chain(product_id)
        )
        reference_platforms_ready = self._reference_platforms_ready(
            copy_matrix, video_project
        )
        input_ready = all(
            (
                context.context_ready,
                context.content_chain_ready,
                context.marketing_strategy_id is not None,
                context.copy_matrix_id is not None,
                context.video_project_id is not None,
                reference_platforms_ready,
            )
        )
        provider_configured = self._provider_configured()
        contract_ready = True
        missing = list(context.missing_requirements)
        if not reference_platforms_ready:
            missing.append("supported_reference_platforms")
        if not provider_configured:
            missing.append("provider_configuration")
            missing.extend(qwen_missing_requirements(self.settings))
        if not self.settings.enable_growth_execution:
            missing.append("growth_execution")
        ready_for_execution = all(
            (
                input_ready,
                provider_configured,
                self.settings.enable_growth_execution,
                contract_ready,
            )
        )
        return GrowthRecommendationPreflightRead(
            product_id=product_id,
            context_digest=context.context_digest,
            marketing_strategy_id=context.marketing_strategy_id,
            copy_matrix_id=context.copy_matrix_id,
            video_project_id=context.video_project_id,
            input_ready=input_ready,
            provider_configured=provider_configured,
            execution_enabled=self.settings.enable_growth_execution,
            contract_ready=contract_ready,
            ready_for_execution=ready_for_execution,
            missing_requirements=list(dict.fromkeys(missing)),
            provider_label=GROWTH_PROVIDER_LABEL,
            model_label=self.settings.qwen_model,
            cost_notice=GROWTH_COST_NOTICE,
            attribution_notice=context.association_notice,
        )

    def _provider_configured(self) -> bool:
        return qwen_provider_configured(self.settings)

    @staticmethod
    def _reference_platforms_ready(
        copy_matrix: CopyMatrix | None,
        video_project: VideoProject | None,
    ) -> bool:
        try:
            resolve_growth_reference_platforms(copy_matrix, video_project)
        except ValueError:
            return False
        return True
