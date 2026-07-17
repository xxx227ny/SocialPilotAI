from collections.abc import Sequence
from decimal import Decimal

from app.models import AdCampaign
from app.schemas.campaign import CampaignMetricsSchema


class MetricsService:
    """Pure deterministic campaign aggregation with no provider dependency."""

    @staticmethod
    def calculate(campaigns: Sequence[AdCampaign]) -> CampaignMetricsSchema:
        impressions = sum(campaign.impressions for campaign in campaigns)
        clicks = sum(campaign.clicks for campaign in campaigns)
        conversions = sum(campaign.conversions for campaign in campaigns)
        spend = sum((campaign.spend for campaign in campaigns), Decimal("0"))
        revenue = sum((campaign.revenue for campaign in campaigns), Decimal("0"))

        ctr = clicks / impressions if impressions else 0.0
        conversion_rate = conversions / clicks if clicks else 0.0
        cpa = spend / conversions if conversions else None
        roas = revenue / spend if spend else None

        return CampaignMetricsSchema(
            impressions=impressions,
            clicks=clicks,
            conversions=conversions,
            spend=round(float(spend), 2),
            revenue=round(float(revenue), 2),
            ctr=round(ctr, 6),
            conversion_rate=round(conversion_rate, 6),
            cpa=round(float(cpa), 2) if cpa is not None else None,
            roas=round(float(roas), 4) if roas is not None else None,
        )
