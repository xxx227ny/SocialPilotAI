from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import AdCampaign, CopyMatrix, MarketingStrategy, VideoProject
from app.repositories.campaign import CampaignRepository
from app.repositories.copy import CopyMatrixRepository
from app.repositories.product import ProductRepository
from app.repositories.strategy import MarketingStrategyRepository
from app.repositories.video import VideoProjectRepository
from app.schemas.growth import (
    FeedbackContextRead,
    FeedbackPlatformMetrics,
)
from app.services.metrics_service import MetricsService

ASSOCIATION_NOTICE = (
    "Campaign metrics are associated with this Product only. The selected "
    "MarketingStrategy, CopyMatrix, and VideoProject form an exact reference "
    "chain for a later stage; they are not persisted campaign attribution. "
    "VideoProject has no MarketingBrief foreign key."
)


class FeedbackContextService:
    """Build a deterministic, read-only context without resolving a Provider."""

    def __init__(self, session: Session) -> None:
        self.product_repository = ProductRepository(session)
        self.campaign_repository = CampaignRepository(session)
        self.strategy_repository = MarketingStrategyRepository(session)
        self.copy_repository = CopyMatrixRepository(session)
        self.video_repository = VideoProjectRepository(session)

    def get(self, product_id: int) -> FeedbackContextRead:
        context, _, _, _ = self.get_with_validated_chain(product_id)
        return context

    def get_with_validated_chain(
        self,
        product_id: int,
    ) -> tuple[
        FeedbackContextRead,
        MarketingStrategy | None,
        CopyMatrix | None,
        VideoProject | None,
    ]:
        """Return the public Context plus its already-validated atomic chain."""
        if self.product_repository.get(product_id) is None:
            raise AppError("Product not found", status_code=404)

        campaigns = self.campaign_repository.list_by_product(product_id)
        campaign_ids = sorted(campaign.id for campaign in campaigns)
        platforms, platform_metrics = self._platform_metrics(campaigns)
        overall_metrics = (
            MetricsService.calculate(campaigns) if campaigns else None
        )
        date_from = min((campaign.date for campaign in campaigns), default=None)
        date_to = max((campaign.date for campaign in campaigns), default=None)
        metrics_ready = bool(campaigns)

        project = self.video_repository.get_latest_by_product(product_id)
        strategy, copy_matrix, chain_missing = self._exact_content_chain(
            product_id, project
        )
        content_chain_ready = not chain_missing
        missing_requirements = (
            ([] if metrics_ready else ["campaign_data"]) + chain_missing
        )
        context_digest = self._digest(
            product_id=product_id,
            campaigns=campaigns,
            project=project,
            strategy=strategy,
            copy_matrix=copy_matrix,
            content_chain_ready=content_chain_ready,
            chain_missing=chain_missing,
        )

        context = FeedbackContextRead(
            product_id=product_id,
            context_digest=context_digest,
            campaign_ids=campaign_ids,
            campaign_count=len(campaign_ids),
            date_from=date_from,
            date_to=date_to,
            platforms=platforms,
            overall_metrics=overall_metrics,
            platform_metrics=platform_metrics,
            marketing_strategy_id=(
                strategy.id if content_chain_ready and strategy else None
            ),
            copy_matrix_id=(
                copy_matrix.id
                if content_chain_ready and copy_matrix
                else None
            ),
            video_project_id=(
                project.id if content_chain_ready and project else None
            ),
            content_chain_ready=content_chain_ready,
            association_notice=ASSOCIATION_NOTICE,
            context_ready=metrics_ready and content_chain_ready,
            metrics_ready=metrics_ready,
            missing_requirements=missing_requirements,
        )
        if not content_chain_ready:
            return context, None, None, None
        return context, strategy, copy_matrix, project

    def _exact_content_chain(
        self,
        product_id: int,
        project: VideoProject | None,
    ) -> tuple[
        MarketingStrategy | None,
        CopyMatrix | None,
        list[str],
    ]:
        if project is None:
            return None, None, ["video_project"]

        strategy = self.strategy_repository.get(
            project.marketing_strategy_id
        )
        copy_matrix = self.copy_repository.get(project.copy_matrix_id)
        missing: list[str] = []
        if strategy is None:
            missing.append("marketing_strategy")
        if copy_matrix is None:
            missing.append("copy_matrix")
        if (
            project.product_id != product_id
            or strategy is not None
            and strategy.product_id != product_id
            or copy_matrix is not None
            and copy_matrix.product_id != product_id
            or copy_matrix is not None
            and copy_matrix.marketing_strategy_id
            != project.marketing_strategy_id
        ):
            missing.append("exact_content_chain")
        return strategy, copy_matrix, missing

    @staticmethod
    def _platform_metrics(
        campaigns: Sequence[AdCampaign],
    ) -> tuple[list[str], list[FeedbackPlatformMetrics]]:
        grouped: dict[str, list[AdCampaign]] = {}
        for campaign in campaigns:
            grouped.setdefault(campaign.platform, []).append(campaign)
        platforms = sorted(grouped, key=lambda value: (value.casefold(), value))
        return (
            platforms,
            [
                FeedbackPlatformMetrics(
                    platform=platform,
                    metrics=MetricsService.calculate(grouped[platform]),
                )
                for platform in platforms
            ],
        )

    @staticmethod
    def _digest(
        *,
        product_id: int,
        campaigns: Sequence[AdCampaign],
        project: VideoProject | None,
        strategy: MarketingStrategy | None,
        copy_matrix: CopyMatrix | None,
        content_chain_ready: bool,
        chain_missing: Sequence[str],
    ) -> str:
        payload = {
            "version": "v1",
            "product_id": product_id,
            "campaigns": [
                {
                    "id": campaign.id,
                    "date": campaign.date.isoformat(),
                    "platform": campaign.platform,
                    "impressions": campaign.impressions,
                    "clicks": campaign.clicks,
                    "conversions": campaign.conversions,
                    "spend": FeedbackContextService._decimal(campaign.spend),
                    "revenue": FeedbackContextService._decimal(
                        campaign.revenue
                    ),
                }
                for campaign in sorted(campaigns, key=lambda item: item.id)
            ],
            "content_chain": {
                "video_project_id": project.id if project else None,
                "marketing_strategy_id": (
                    project.marketing_strategy_id if project else None
                ),
                "copy_matrix_id": (
                    project.copy_matrix_id if project else None
                ),
                "strategy_found": strategy is not None,
                "copy_matrix_found": copy_matrix is not None,
                "strategy_matches_product": (
                    strategy is not None
                    and strategy.product_id == product_id
                ),
                "copy_matrix_matches_product": (
                    copy_matrix is not None
                    and copy_matrix.product_id == product_id
                ),
                "strategy_reference_consistent": (
                    project is not None
                    and copy_matrix is not None
                    and copy_matrix.marketing_strategy_id
                    == project.marketing_strategy_id
                ),
                "missing": sorted(chain_missing),
                "ready": content_chain_ready,
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
    def _decimal(value: Decimal) -> str:
        return format(value, "f")
