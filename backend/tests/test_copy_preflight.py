import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.core.config import Settings, get_settings
from app.main import app
from app.models import CopyMatrix, MarketingBrief, MarketingStrategy
from app.providers.base import TextGenerationProvider


def configured_settings(*, execution_enabled: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        qwen_api_key="safe-test-placeholder",
        dashscope_api_key=None,
        enable_copy_execution=execution_enabled,
    )


def create_product(client: TestClient, name: str) -> dict:
    response = client.post(
        "/api/v1/products",
        json={
            "name": name,
            "category": "Portable Kitchen Appliance",
            "description": "A complete product description for copy preflight.",
            "selling_points": ["Portable design", "USB rechargeable"],
            "target_markets": ["US"],
        },
    )
    assert response.status_code == 201
    return response.json()


def create_task(
    client: TestClient,
    product_id: int,
    *,
    platforms: list[str] | None = None,
) -> dict:
    response = client.post(
        "/api/v1/marketing-tasks",
        json={
            "product_id": product_id,
            "audience": "Cross-border commuters",
            "language": "English",
            "platforms": platforms or ["TikTok"],
            "tone": "Clear and energetic",
            "objective": "Prepare platform copy",
        },
    )
    assert response.status_code == 201
    return response.json()


def add_strategy(
    db_session: Session,
    product_id: int,
    positioning: str,
) -> MarketingStrategy:
    strategy = MarketingStrategy(
        product_id=product_id,
        positioning=positioning,
        audience_insights=["Audience insight"],
        angles=["Marketing angle"],
        risks=["Avoid unsupported claims"],
        evidence=["Product evidence"],
    )
    db_session.add(strategy)
    db_session.commit()
    db_session.refresh(strategy)
    return strategy


def test_copy_preflight_uses_exact_sources_without_provider_or_write(
    client: TestClient,
    db_session: Session,
) -> None:
    product = create_product(client, "Exact Source Product")
    requested_task = create_task(client, product["id"], platforms=["TikTok"])
    latest_task = create_task(client, product["id"], platforms=["Facebook"])
    requested_strategy = add_strategy(
        db_session, product["id"], "Requested strategy positioning"
    )
    latest_strategy = add_strategy(
        db_session, product["id"], "Latest strategy must not be selected"
    )
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Copy preflight must not resolve Provider")

    app.dependency_overrides[get_settings] = configured_settings
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    try:
        response = client.get(
            f"/api/v1/marketing-tasks/{requested_task['id']}"
            f"/strategies/{requested_strategy.id}/copy-preflight"
        )

        assert latest_task["id"] > requested_task["id"]
        assert latest_strategy.id > requested_strategy.id
        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == requested_task["id"]
        assert data["strategy_id"] == requested_strategy.id
        assert data["product_id"] == product["id"]
        assert data["platforms"] == ["TikTok"]
        assert data["strategy_summary"]["positioning"] == (
            "Requested strategy positioning"
        )
        assert data["input_ready"] is True
        assert data["provider_configured"] is True
        assert data["execution_enabled"] is True
        assert data["contract_ready"] is True
        assert data["ready_for_execution"] is True
        assert data["association_persisted"] is False
        assert "marketing_strategy_id" in data["association_notice"]
        assert (
            "brief_aware_exact_strategy_copy_contract"
            not in data["missing_requirements"]
        )
        assert "safe-test-placeholder" not in response.text
        assert provider_resolutions == 0
        assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)


def test_copy_preflight_accepts_legacy_qwen_key_without_exposing_it(
    client: TestClient,
    db_session: Session,
) -> None:
    product = create_product(client, "Legacy Configuration Product")
    task = create_task(client, product["id"])
    strategy = add_strategy(db_session, product["id"], "Valid positioning")
    legacy_secret = "safe-legacy-placeholder"
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        qwen_api_key=None,
        dashscope_api_key=legacy_secret,
        enable_copy_execution=True,
    )
    try:
        response = client.get(
            f"/api/v1/marketing-tasks/{task['id']}"
            f"/strategies/{strategy.id}/copy-preflight"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["provider_configured"] is True
        assert data["input_ready"] is True
        assert data["contract_ready"] is True
        assert data["ready_for_execution"] is True
        assert data["missing_requirements"] == []
        assert legacy_secret not in response.text
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_copy_preflight_rejects_cross_product_pair(
    client: TestClient,
    db_session: Session,
) -> None:
    first = create_product(client, "First Product")
    second = create_product(client, "Second Product")
    task = create_task(client, first["id"])
    strategy = add_strategy(db_session, second["id"], "Second positioning")
    app.dependency_overrides[get_settings] = configured_settings
    try:
        response = client.get(
            f"/api/v1/marketing-tasks/{task['id']}"
            f"/strategies/{strategy.id}/copy-preflight"
        )

        assert response.status_code == 409
        assert response.json()["error"]["message"] == (
            "Marketing task and Strategy belong to different Products"
        )
        assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_copy_preflight_reports_missing_task_strategy_and_product(
    client: TestClient,
    db_session: Session,
) -> None:
    product = create_product(client, "Missing Sources Product")
    task = create_task(client, product["id"])
    strategy = add_strategy(db_session, product["id"], "Valid positioning")
    orphan = MarketingBrief(
        product_id=999,
        audience="Target markets [US]. Audience",
        language="English",
        platforms=["TikTok"],
        tone="Clear",
        objective="Awareness",
    )
    db_session.add(orphan)
    db_session.commit()
    app.dependency_overrides[get_settings] = configured_settings
    try:
        missing_task = client.get(
            f"/api/v1/marketing-tasks/999/strategies/{strategy.id}/copy-preflight"
        )
        missing_strategy = client.get(
            f"/api/v1/marketing-tasks/{task['id']}/strategies/999/copy-preflight"
        )
        missing_product = client.get(
            f"/api/v1/marketing-tasks/{orphan.id}"
            f"/strategies/{strategy.id}/copy-preflight"
        )

        assert missing_task.status_code == 404
        assert missing_strategy.status_code == 404
        assert missing_product.status_code == 404
        assert missing_product.json()["error"]["message"] == (
            "Marketing task Product not found"
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.parametrize("invalid_platforms", [[], ["YouTube"]])
def test_copy_preflight_blocks_invalid_platform_and_strategy_data(
    client: TestClient,
    db_session: Session,
    invalid_platforms: list[str],
) -> None:
    product = create_product(client, "Invalid Input Product")
    task = create_task(client, product["id"])
    strategy = add_strategy(db_session, product["id"], "Valid positioning")
    task_row = db_session.get(MarketingBrief, task["id"])
    task_row.__dict__["platforms"] = invalid_platforms
    strategy.__dict__["angles"] = ["  "]
    app.dependency_overrides[get_settings] = configured_settings
    try:
        response = client.get(
            f"/api/v1/marketing-tasks/{task['id']}"
            f"/strategies/{strategy.id}/copy-preflight"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["input_ready"] is False
        assert data["contract_ready"] is True
        assert "supported_platforms" in data["missing_requirements"]
        assert "strategy_schema" in data["missing_requirements"]
        assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_copy_preflight_reports_config_and_execution_without_secrets(
    client: TestClient,
    db_session: Session,
) -> None:
    product = create_product(client, "Configuration Product")
    task = create_task(client, product["id"])
    strategy = add_strategy(db_session, product["id"], "Valid positioning")
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        qwen_api_key=None,
        dashscope_api_key=None,
        token_plan_api_key_file="",
    )
    try:
        response = client.get(
            f"/api/v1/marketing-tasks/{task['id']}"
            f"/strategies/{strategy.id}/copy-preflight"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["input_ready"] is True
        assert data["provider_configured"] is False
        assert data["execution_enabled"] is False
        assert data["contract_ready"] is True
        assert data["ready_for_execution"] is False
        assert "provider_configuration" in data["missing_requirements"]
        assert "copy_execution" in data["missing_requirements"]
        serialized = response.text.casefold()
        for forbidden in (
            "api_key",
            "token",
            "workspace_id",
            "authorization",
            "safe-test-placeholder",
        ):
            assert forbidden not in serialized
    finally:
        app.dependency_overrides.pop(get_settings, None)
