from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import AdCampaign, DemoScenario
from app.repositories.campaign import CampaignRepository
from app.repositories.copy import CopyMatrixRepository
from app.repositories.product import ProductRepository
from app.repositories.strategy import MarketingStrategyRepository
from app.repositories.video import VideoProjectRepository
from app.schemas.dashboard import (
    DashboardCopyMatrixSchema,
    DashboardGrowthSchema,
    DashboardSnapshotSchema,
    DashboardStrategySchema,
    DemoMetadataSchema,
    PipelineStatus,
    PipelineStepSchema,
    PlatformMetricsSchema,
)
from app.schemas.growth import GrowthRecommendation
from app.schemas.product import ProductRead
from app.schemas.video import VideoProjectSchema
from app.services.metrics_service import MetricsService


class DashboardService:
    """Read stored workflow data without invoking any generation service."""

    def __init__(self, session: Session) -> None:
        self.product_repository = ProductRepository(session)
        self.strategy_repository = MarketingStrategyRepository(session)
        self.copy_repository = CopyMatrixRepository(session)
        self.video_repository = VideoProjectRepository(session)
        self.campaign_repository = CampaignRepository(session)

    def get_snapshot(
        self, product_id: int, demo_scenario: DemoScenario | None = None
    ) -> DashboardSnapshotSchema:
        product = self.product_repository.get(product_id)
        if product is None:
            raise AppError("Product not found", status_code=404)

        if demo_scenario is None:
            strategy = self.strategy_repository.get_latest_by_product(product_id)
            copy_matrix = self.copy_repository.get_latest_by_product(product_id)
            video_project = self.video_repository.get_latest_by_product(product_id)
            campaigns = self.campaign_repository.list_by_product(product_id)
            recommendation = None
        else:
            strategy = self.strategy_repository.get(
                demo_scenario.marketing_strategy_id
            )
            copy_matrix = self.copy_repository.get(demo_scenario.copy_matrix_id)
            video_project = self.video_repository.get(
                demo_scenario.video_project_id
            )
            campaigns = self.campaign_repository.list_by_ids(
                demo_scenario.campaign_ids
            )
            recommendation = GrowthRecommendation.model_validate(
                demo_scenario.growth_recommendation
            )

        metrics = MetricsService.calculate(campaigns) if campaigns else None
        platform_metrics = self._calculate_platform_metrics(campaigns)
        growth_status = self._growth_status(metrics is not None, recommendation)
        pipeline = [
            PipelineStepSchema(
                key="product", label="Product", status="complete", source_id=product.id
            ),
            PipelineStepSchema(
                key="strategy",
                label="Marketing Strategy",
                status="complete" if strategy else "missing",
                source_id=strategy.id if strategy else None,
            ),
            PipelineStepSchema(
                key="copy",
                label="Copy Matrix",
                status="complete" if copy_matrix else "missing",
                source_id=copy_matrix.id if copy_matrix else None,
            ),
            PipelineStepSchema(
                key="video",
                label="Video Plan",
                status="complete" if video_project else "missing",
                source_id=video_project.id if video_project else None,
            ),
            PipelineStepSchema(
                key="growth",
                label="Growth Optimization",
                status=growth_status,
                source_id=demo_scenario.id if demo_scenario else None,
            ),
        ]
        demo_metadata = (
            DemoMetadataSchema(
                slug=demo_scenario.slug,
                label=demo_scenario.label,
                source="preset_fixture",
                fixture_version=demo_scenario.fixture_version,
            )
            if demo_scenario
            else None
        )
        return DashboardSnapshotSchema(
            data_source="demo_snapshot" if demo_scenario else "stored_records",
            demo=demo_metadata,
            product=ProductRead.model_validate(product),
            strategy=(
                DashboardStrategySchema.model_validate(strategy)
                if strategy
                else None
            ),
            copy_matrix=(
                DashboardCopyMatrixSchema.model_validate(copy_matrix)
                if copy_matrix
                else None
            ),
            video_project=(
                VideoProjectSchema.model_validate(video_project)
                if video_project
                else None
            ),
            growth=DashboardGrowthSchema(
                status=growth_status,
                metrics=metrics,
                platform_metrics=platform_metrics,
                recommendation=recommendation,
            ),
            pipeline=pipeline,
        )

    @staticmethod
    def _growth_status(
        has_metrics: bool, recommendation: GrowthRecommendation | None
    ) -> PipelineStatus:
        if has_metrics and recommendation is not None:
            return "complete"
        if has_metrics or recommendation is not None:
            return "partial"
        return "missing"

    @staticmethod
    def _calculate_platform_metrics(
        campaigns: list[AdCampaign],
    ) -> list[PlatformMetricsSchema]:
        campaigns_by_platform: dict[str, list[AdCampaign]] = {}
        for campaign in campaigns:
            campaigns_by_platform.setdefault(campaign.platform, []).append(campaign)
        return [
            PlatformMetricsSchema(
                platform=platform,
                metrics=MetricsService.calculate(platform_campaigns),
            )
            for platform, platform_campaigns in campaigns_by_platform.items()
        ]
