import json

import pytest
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
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.providers.base import TextGenerationProvider
from app.repositories.strategy import MarketingStrategyRepository
from app.schemas.strategy import MarketingStrategySchema


class FakeStrategyProvider(TextGenerationProvider):
    def generate(self, prompt: str) -> str:
        assert "Portable Blender" in prompt
        return json.dumps(
            {
                "positioning": "Everyday portable nutrition helper.",
                "audience_insights": ["Young professionals need speed."],
                "angles": ["Blend between meetings"],
                "risks": ["Do not promise medical outcomes."],
                "evidence": ["Portable design and USB charging."],
            }
        )


class InvalidWhitespaceStrategyProvider(TextGenerationProvider):
    def generate(self, prompt: str) -> str:
        assert "Portable Blender" in prompt
        return json.dumps(
            {
                "positioning": "SENSITIVE_PROVIDER_RAW_PAYLOAD",
                "audience_insights": ["Audience"],
                "angles": [" \t\n "],
                "risks": ["Risk"],
                "evidence": ["Evidence"],
            }
        )


class RecordingTaskProvider(TextGenerationProvider):
    def __init__(self, result: str | None = None) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.result = result or json.dumps(
            {
                "positioning": "Brief-aware positioning.",
                "audience_insights": ["Requested audience insight."],
                "angles": ["Requested platform angle."],
                "risks": ["Avoid unsupported claims."],
                "evidence": ["Uses supplied product evidence."],
            }
        )

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        return self.result


def enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        dashscope_api_key="safe-test-placeholder",
        enable_strategy_execution=True,
    )


def create_marketing_task(
    client: TestClient,
    product_id: int,
    *,
    audience: str = "Cross-border professionals",
    platforms: list[str] | None = None,
    language: str = "English",
    tone: str = "Clear and practical",
    objective: str = "Build awareness",
) -> dict:
    response = client.post(
        "/api/v1/marketing-tasks",
        json={
            "product_id": product_id,
            "audience": audience,
            "language": language,
            "platforms": platforms or ["TikTok", "Instagram"],
            "tone": tone,
            "objective": objective,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_strategy_api_returns_structured_result(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    app.dependency_overrides[get_text_generation_provider] = FakeStrategyProvider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        product = client.post("/api/v1/products", json=product_payload).json()

        response = client.post(f"/api/v1/products/{product['id']}/strategy")

        assert response.status_code == 200
        data = response.json()
        assert data | {
            "id": data["id"],
            "product_id": data["product_id"],
            "created_at": data["created_at"],
        } == {
            "id": data["id"],
            "product_id": product["id"],
            "created_at": data["created_at"],
            "positioning": "Everyday portable nutrition helper.",
            "audience_insights": ["Young professionals need speed."],
            "angles": ["Blend between meetings"],
            "risks": ["Do not promise medical outcomes."],
            "evidence": ["Portable design and USB charging."],
        }
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)
        app.dependency_overrides.pop(get_settings, None)


def test_strategy_api_rejects_blank_provider_item_safely(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    app.dependency_overrides[
        get_text_generation_provider
    ] = InvalidWhitespaceStrategyProvider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        product = client.post("/api/v1/products", json=product_payload).json()

        response = client.post(f"/api/v1/products/{product['id']}/strategy")

        assert response.status_code == 502
        response_text = response.text
        assert response.json()["error"]["message"] == (
            "Qwen returned invalid strategy data"
        )
        assert "SENSITIVE_PROVIDER_RAW_PAYLOAD" not in response_text
        assert "Traceback" not in response_text
        for model in (
            MarketingStrategy,
            CopyMatrix,
            VideoProject,
            VideoRenderTask,
            VideoRenderArtifact,
        ):
            assert db_session.scalar(select(func.count(model.id))) == 0
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)
        app.dependency_overrides.pop(get_settings, None)


def add_strategy(
    db_session: Session, product_id: int, positioning: str
) -> MarketingStrategy:
    return MarketingStrategyRepository(db_session).create(
        product_id,
        MarketingStrategySchema(
            positioning=positioning,
            audience_insights=["Audience"],
            angles=["Angle"],
            risks=["Risk"],
            evidence=["Evidence"],
        ),
    )


def test_latest_strategy_requires_existing_product(client: TestClient) -> None:
    response = client.get("/api/v1/products/999/strategies/latest")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Product not found"


def test_latest_strategy_reports_empty_result(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()

    response = client.get(
        f"/api/v1/products/{product['id']}/strategies/latest"
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Marketing strategy not found"


def test_latest_strategy_is_product_scoped_and_read_only(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    first_product = client.post("/api/v1/products", json=product_payload).json()
    second_payload = {**product_payload, "name": "Second Product"}
    second_product = client.post("/api/v1/products", json=second_payload).json()
    add_strategy(db_session, first_product["id"], "Older positioning")
    latest = add_strategy(db_session, first_product["id"], "Latest positioning")
    add_strategy(db_session, second_product["id"], "Other product positioning")
    provider_calls = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("Latest strategy read must not resolve a Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    counts_before = {
        model: db_session.scalar(select(func.count(model.id)))
        for model in (
            MarketingStrategy,
            CopyMatrix,
            VideoProject,
            VideoRenderTask,
            VideoRenderArtifact,
        )
    }

    response = client.get(
        f"/api/v1/products/{first_product['id']}/strategies/latest"
    )

    assert response.status_code == 200
    assert response.json()["id"] == latest.id
    assert response.json()["product_id"] == first_product["id"]
    assert response.json()["positioning"] == "Latest positioning"
    assert provider_calls == 0
    for model, count in counts_before.items():
        assert db_session.scalar(select(func.count(model.id))) == count


def test_both_execution_routes_default_disabled_before_provider_resolution(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    task = create_marketing_task(client, product["id"])
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Disabled execution must stop before Provider")

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider

    task_response = client.post(
        f"/api/v1/marketing-tasks/{task['id']}/strategy"
    )
    product_response = client.post(
        f"/api/v1/products/{product['id']}/strategy"
    )

    assert task_response.status_code == 503
    assert product_response.status_code == 503
    assert task_response.json()["error"]["message"] == (
        "Strategy execution is disabled by the server"
    )
    assert provider_resolutions == 0
    assert db_session.scalar(select(func.count(MarketingStrategy.id))) == 0


def test_task_bound_strategy_uses_requested_brief_and_returns_honest_contract(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    requested = create_marketing_task(
        client,
        product["id"],
        audience="Requested audience",
        language="French",
        tone="Warm",
        objective="Conversion",
    )
    latest = create_marketing_task(
        client,
        product["id"],
        audience="Latest task must not be selected",
        language="Japanese",
        tone="Formal",
        objective="Awareness",
    )
    provider = RecordingTaskProvider()
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider

    response = client.post(
        f"/api/v1/marketing-tasks/{requested['id']}/strategy"
    )

    assert latest["id"] > requested["id"]
    assert response.status_code == 200
    data = response.json()
    assert data["source_task_id"] == requested["id"]
    assert data["source_product_id"] == product["id"]
    assert data["source_kind"] == "marketing_brief"
    assert data["association_persisted"] is False
    assert "not persisted" in data["association_notice"]
    assert data["strategy"]["product_id"] == product["id"]
    assert provider.calls == 1
    prompt = provider.prompts[0]
    for expected in (
        product["name"],
        product["category"],
        product["description"],
        *product["selling_points"],
        str(requested["id"]),
        "US",
        "TikTok",
        "Instagram",
        "Requested audience",
        "French",
        "Warm",
        "Conversion",
    ):
        assert expected in prompt
    assert "Latest task must not be selected" not in prompt
    assert db_session.scalar(select(func.count(MarketingStrategy.id))) == 1
    for model in (
        CopyMatrix,
        VideoProject,
        VideoRenderTask,
        VideoRenderArtifact,
    ):
        assert db_session.scalar(select(func.count(model.id))) == 0


def test_task_bound_preflight_and_provider_configuration_block_without_calls(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    blocked = MarketingBrief(
        product_id=product["id"],
        audience="Audience without a persisted market snapshot",
        language="English",
        platforms=["TikTok"],
        tone="Clear",
        objective="Awareness",
    )
    db_session.add(blocked)
    db_session.commit()
    provider = RecordingTaskProvider()
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    app.dependency_overrides[get_settings] = enabled_settings

    blocked_response = client.post(
        f"/api/v1/marketing-tasks/{blocked.id}/strategy"
    )

    assert blocked_response.status_code == 422
    assert provider.calls == 0

    valid_task = create_marketing_task(client, product["id"])
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        dashscope_api_key=None,
        enable_strategy_execution=True,
    )
    unconfigured_response = client.post(
        f"/api/v1/marketing-tasks/{valid_task['id']}/strategy"
    )

    assert unconfigured_response.status_code == 503
    assert unconfigured_response.json()["error"]["message"] == (
        "Qwen provider is not configured"
    )
    assert provider.calls == 0
    assert db_session.scalar(select(func.count(MarketingStrategy.id))) == 0


def test_task_bound_invalid_output_is_safe_and_writes_nothing(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    task = create_marketing_task(client, product["id"])
    provider = RecordingTaskProvider(
        json.dumps(
            {
                "positioning": "SENSITIVE_RAW_PROVIDER_CONTENT",
                "audience_insights": ["Audience"],
                "angles": ["   "],
                "risks": ["Risk"],
                "evidence": ["Evidence"],
            }
        )
    )
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider

    response = client.post(
        f"/api/v1/marketing-tasks/{task['id']}/strategy"
    )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Qwen returned invalid strategy data"
    )
    assert "SENSITIVE_RAW_PROVIDER_CONTENT" not in response.text
    assert "Traceback" not in response.text
    assert provider.calls == 1
    for model in (
        MarketingStrategy,
        CopyMatrix,
        VideoProject,
        VideoRenderTask,
        VideoRenderArtifact,
    ):
        assert db_session.scalar(select(func.count(model.id))) == 0


@pytest.mark.parametrize("task_id", [999])
def test_task_bound_missing_task_is_safe(
    client: TestClient, task_id: int
) -> None:
    provider = RecordingTaskProvider()
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider

    response = client.post(f"/api/v1/marketing-tasks/{task_id}/strategy")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Marketing task not found"
    assert provider.calls == 0
