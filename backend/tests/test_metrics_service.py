from datetime import date
from decimal import Decimal

from app.models import AdCampaign
from app.services.metrics_service import MetricsService


def campaign(
    impressions: int,
    clicks: int,
    conversions: int,
    spend: str,
    revenue: str,
) -> AdCampaign:
    return AdCampaign(
        product_id=1,
        platform="TikTok",
        campaign_name="Campaign",
        date=date(2026, 7, 1),
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        spend=Decimal(spend),
        revenue=Decimal(revenue),
    )


def test_metrics_are_calculated_from_aggregate_totals() -> None:
    metrics = MetricsService.calculate(
        [
            campaign(100, 10, 1, "10", "40"),
            campaign(900, 45, 9, "90", "180"),
        ]
    )

    assert metrics.impressions == 1000
    assert metrics.clicks == 55
    assert metrics.conversions == 10
    assert metrics.spend == 100
    assert metrics.revenue == 220
    assert metrics.ctr == 0.055
    assert metrics.conversion_rate == 0.181818
    assert metrics.cpa == 10
    assert metrics.roas == 2.2


def test_metrics_protect_zero_denominators() -> None:
    metrics = MetricsService.calculate([campaign(0, 0, 0, "0", "0")])

    assert metrics.ctr == 0
    assert metrics.conversion_rate == 0
    assert metrics.cpa is None
    assert metrics.roas is None
