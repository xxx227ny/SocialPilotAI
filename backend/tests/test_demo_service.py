from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DemoScenario, Product
from app.services.demo_service import DemoService


def test_demo_prepare_is_idempotent_and_uses_explicit_scenario_source(
    db_session: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "app_environment", "development")
    same_name_product = Product(
        name="Portable Blender Demo",
        category="User product",
        description="This record must not identify the demo.",
        selling_points=["User-owned"],
        target_markets=["USA"],
    )
    db_session.add(same_name_product)
    db_session.commit()

    first = DemoService(db_session).prepare()
    second = DemoService(db_session).prepare()

    scenario = db_session.scalar(select(DemoScenario))
    assert scenario is not None
    assert scenario.source == "preset_fixture"
    assert scenario.product_id != same_name_product.id
    assert first.product.id == second.product.id == scenario.product_id
    assert first.demo is not None
    assert first.demo.badge == "Demo Snapshot"
    assert first.demo.ai_calls == 0
    assert first.demo.notice == "使用预置演示数据"
    assert db_session.scalar(select(func.count()).select_from(DemoScenario)) == 1
    assert db_session.scalar(select(func.count()).select_from(Product)) == 2


def test_demo_metrics_use_aggregate_campaign_totals(
    db_session: Session, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "app_environment", "development")

    snapshot = DemoService(db_session).prepare()

    metrics = snapshot.growth.metrics
    assert metrics is not None
    assert metrics.impressions == 250000
    assert metrics.clicks == 11300
    assert metrics.conversions == 616
    assert metrics.spend == 6048
    assert metrics.revenue == 21888
    assert metrics.ctr == 0.0452
    assert metrics.roas == 3.619
