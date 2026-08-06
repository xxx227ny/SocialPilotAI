from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    CopyMatrix,
    MarketingBrief,
    MarketingStrategy,
    Product,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.services.strategy_preflight import StrategyPreflightService


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        qwen_api_key="safe-test-placeholder",
        dashscope_api_key=None,
        qwen_model="qwen-plus",
        enable_strategy_execution=True,
    )


def create_task(client: TestClient, product_payload: dict[str, object]) -> dict:
    product = client.post("/api/v1/products", json=product_payload).json()
    response = client.post(
        "/api/v1/marketing-tasks",
        json={
            "product_id": product["id"],
            "audience": "Cross-border consumers",
            "language": "English",
            "platforms": ["TikTok", "Instagram"],
            "tone": "Clear and trustworthy",
            "objective": "Prepare social marketing input",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_valid_preflight_is_read_only(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    task = create_task(client, product_payload)
    provider_calls = 0

    def forbidden_provider() -> None:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("Preflight must not resolve a Provider")

    app.dependency_overrides[get_settings] = configured_settings
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    response = client.get(
        f"/api/v1/marketing-tasks/{task['id']}/strategy-preflight"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is True
    assert data["input_ready"] is True
    assert data["ready_for_execution"] is True
    assert data["missing_requirements"] == []
    assert data["task_id"] == task["id"]
    assert data["product_id"] == task["product_id"]
    assert data["target_market_snapshot"] == ["US"]
    assert data["platforms"] == ["TikTok", "Instagram"]
    assert data["audience"] == "Cross-border consumers"
    assert data["provider_label"] == "Alibaba Cloud Bailian Qwen"
    assert data["model_label"] == "qwen-plus"
    assert data["provider_configured"] is True
    assert data["execution_enabled"] is True
    assert data["preflight_only"] is True
    assert data["execution_will_call_ai"] is True
    assert data["execution_will_create_strategy"] is True
    assert "safe-test-placeholder" not in response.text
    assert provider_calls == 0

    for model in (
        MarketingStrategy,
        CopyMatrix,
        VideoProject,
        VideoRenderTask,
        VideoRenderArtifact,
    ):
        assert db_session.scalar(select(func.count(model.id))) == 0


def test_missing_task_and_product_fail_safely(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = configured_settings
    missing_task = client.get("/api/v1/marketing-tasks/999/strategy-preflight")
    assert missing_task.status_code == 404

    orphan = MarketingBrief(
        product_id=999,
        audience="Target markets [US]. Cross-border consumers",
        language="English",
        platforms=["TikTok"],
        tone="Clear",
        objective="Awareness",
    )
    db_session.add(orphan)
    db_session.commit()

    orphan_response = client.get(
        f"/api/v1/marketing-tasks/{orphan.id}/strategy-preflight"
    )
    assert orphan_response.status_code == 404
    assert orphan_response.json()["error"]["message"] == "Product not found"


def test_preflight_reports_missing_and_invalid_business_input(
    db_session: Session,
) -> None:
    product = Product(
        name="Valid Product",
        category="Category",
        description="Useful product description",
        selling_points=["Useful point"],
        target_markets=[],
    )
    db_session.add(product)
    db_session.flush()
    task = MarketingBrief(
        product_id=product.id,
        audience="Audience",
        language="English",
        platforms=["TikTok"],
        tone="Clear",
        objective="Awareness",
    )
    db_session.add(task)
    db_session.commit()
    task.__dict__["audience"] = ""
    task.__dict__["language"] = ""
    task.__dict__["tone"] = ""
    task.__dict__["objective"] = ""
    task.__dict__["platforms"] = ["YouTube"]

    result = StrategyPreflightService(
        db_session, configured_settings()
    ).run(task.id)

    assert result.ready is False
    assert set(result.missing_requirements) >= {
        "target_market_snapshot",
        "supported_platforms",
        "audience",
        "language",
        "tone",
        "objective",
    }


def test_provider_configuration_is_boolean_and_secret_safe(
    client: TestClient,
    product_payload: dict[str, object],
) -> None:
    task = create_task(client, product_payload)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        qwen_api_key=None,
        dashscope_api_key=None,
        qwen_model="qwen-plus",
        enable_strategy_execution=True,
    )

    response = client.get(
        f"/api/v1/marketing-tasks/{task['id']}/strategy-preflight"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is False
    assert data["provider_configured"] is False
    assert data["execution_enabled"] is True
    assert "provider_configuration" in data["missing_requirements"]
    serialized = response.text.casefold()
    for forbidden in (
        "safe-test-placeholder",
        "api_key",
        "token",
        "workspace_id",
        "authorization",
    ):
        assert forbidden not in serialized


def test_legacy_dashscope_key_remains_a_compatible_fallback(
    client: TestClient,
    product_payload: dict[str, object],
) -> None:
    task = create_task(client, product_payload)
    legacy_secret = "safe-legacy-placeholder"
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        qwen_api_key=None,
        dashscope_api_key=legacy_secret,
        qwen_model="qwen-plus",
        enable_strategy_execution=True,
    )

    response = client.get(
        f"/api/v1/marketing-tasks/{task['id']}/strategy-preflight"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider_configured"] is True
    assert data["ready"] is True
    assert data["missing_requirements"] == []
    assert legacy_secret not in response.text


def test_provider_type_unavailable_is_not_ready(
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product = Product(**product_payload)
    db_session.add(product)
    db_session.flush()
    task = MarketingBrief(
        product_id=product.id,
        audience="Target markets [US]. Cross-border consumers",
        language="English",
        platforms=["TikTok"],
        tone="Clear",
        objective="Awareness",
    )
    db_session.add(task)
    db_session.commit()

    result = StrategyPreflightService(
        db_session, configured_settings(), provider_type=None
    ).run(task.id)

    assert result.ready is False
    assert "qwen_provider_type" in result.missing_requirements


def test_execution_enabled_defaults_false_and_is_reported_separately(
    client: TestClient,
    product_payload: dict[str, object],
) -> None:
    task = create_task(client, product_payload)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        dashscope_api_key="safe-test-placeholder",
    )

    response = client.get(
        f"/api/v1/marketing-tasks/{task['id']}/strategy-preflight"
    )

    assert Settings(_env_file=None).enable_strategy_execution is False
    assert response.status_code == 200
    data = response.json()
    assert data["input_ready"] is True
    assert data["provider_configured"] is True
    assert data["execution_enabled"] is False
    assert data["ready_for_execution"] is False
    assert data["ready"] is False
    assert "strategy_execution" in data["missing_requirements"]
