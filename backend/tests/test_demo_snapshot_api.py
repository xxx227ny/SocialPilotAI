from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.core.config import settings
from app.main import app
from app.models import AdCampaign, DemoScenario, Product
from app.providers.base import TextGenerationProvider


class ForbiddenSnapshotProvider(TextGenerationProvider):
    def generate(self, prompt: str) -> str:
        raise AssertionError(f"Snapshot must not call a provider: {prompt}")


def prepare_demo(client: TestClient, monkeypatch) -> dict[str, object]:
    monkeypatch.setattr(settings, "app_environment", "development")
    response = client.post("/api/v1/demo/prepare")
    assert response.status_code == 200
    return response.json()


def test_demo_snapshot_returns_existing_complete_snapshot(
    client: TestClient, monkeypatch
) -> None:
    prepared = prepare_demo(client, monkeypatch)

    response = client.get("/api/v1/demo/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body == prepared
    assert body["demo"]["source"] == "preset_fixture"
    assert all(step["status"] == "complete" for step in body["pipeline"])


def test_demo_snapshot_returns_clear_404_when_not_prepared(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/demo/snapshot")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == (
        "Demo snapshot not found; prepare the demo first"
    )


def test_demo_snapshot_is_read_only(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    prepare_demo(client, monkeypatch)
    counts_before = {
        "products": db_session.scalar(select(func.count()).select_from(Product)),
        "campaigns": db_session.scalar(
            select(func.count()).select_from(AdCampaign)
        ),
        "scenarios": db_session.scalar(
            select(func.count()).select_from(DemoScenario)
        ),
    }
    scenario_before = db_session.scalar(select(DemoScenario))
    assert scenario_before is not None
    updated_at_before = scenario_before.updated_at

    response = client.get("/api/v1/demo/snapshot")

    assert response.status_code == 200
    db_session.expire_all()
    counts_after = {
        "products": db_session.scalar(select(func.count()).select_from(Product)),
        "campaigns": db_session.scalar(
            select(func.count()).select_from(AdCampaign)
        ),
        "scenarios": db_session.scalar(
            select(func.count()).select_from(DemoScenario)
        ),
    }
    scenario_after = db_session.scalar(select(DemoScenario))
    assert scenario_after is not None
    assert counts_after == counts_before
    assert scenario_after.updated_at == updated_at_before


def test_demo_snapshot_has_no_provider_dependency(
    client: TestClient, monkeypatch
) -> None:
    prepare_demo(client, monkeypatch)
    app.dependency_overrides[get_text_generation_provider] = (
        ForbiddenSnapshotProvider
    )
    try:
        response = client.get("/api/v1/demo/snapshot")
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 200
    assert response.json()["demo"]["ai_calls"] == 0


def test_platform_metrics_reuse_the_same_campaign_totals(
    client: TestClient, monkeypatch
) -> None:
    prepare_demo(client, monkeypatch)

    response = client.get("/api/v1/demo/snapshot")

    assert response.status_code == 200
    growth = response.json()["growth"]
    totals = growth["metrics"]
    platforms = {
        item["platform"]: item["metrics"]
        for item in growth["platform_metrics"]
    }
    assert platforms["TikTok"] == {
        "impressions": 120000,
        "clicks": 6600,
        "conversions": 396,
        "spend": 3168.0,
        "revenue": 12672.0,
        "ctr": 0.055,
        "conversion_rate": 0.06,
        "cpa": 8.0,
        "roas": 4.0,
    }
    assert platforms["Instagram"]["roas"] == 3.5
    assert platforms["Facebook"]["roas"] == 2.6
    for field in ("impressions", "clicks", "conversions", "spend", "revenue"):
        assert totals[field] == sum(metrics[field] for metrics in platforms.values())
