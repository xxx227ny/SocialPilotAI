import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.main import app
from app.models import (
    CopyMatrix,
    MarketingBrief,
    MarketingStrategy,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderModelError,
    ProviderQuotaError,
    TextGenerationProvider,
)
from app.services.copy_generation_service import CopyGenerationService


class RecordingTaskCopyProvider(TextGenerationProvider):
    def __init__(self, result: str) -> None:
        self.result = result
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.result


class FailingTaskCopyProvider(TextGenerationProvider):
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def generate(self, prompt: str) -> str:
        del prompt
        self.calls += 1
        raise self.error


def enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        dashscope_api_key="safe-test-placeholder",
        enable_copy_execution=True,
    )


def create_product(
    client: TestClient, name: str, markets: list[str] | None = None
) -> dict:
    response = client.post(
        "/api/v1/products",
        json={
            "name": name,
            "category": "Portable Kitchen Appliance",
            "description": "A portable blender for busy cross-border shoppers.",
            "selling_points": ["Portable design", "USB rechargeable"],
            "target_markets": markets or ["US"],
        },
    )
    assert response.status_code == 201
    return response.json()


def create_task(
    client: TestClient,
    product_id: int,
    platforms: list[str],
    *,
    audience: str = "Busy commuters",
) -> dict:
    response = client.post(
        "/api/v1/marketing-tasks",
        json={
            "product_id": product_id,
            "audience": audience,
            "language": "English",
            "platforms": platforms,
            "tone": "Clear and energetic",
            "objective": "Drive product consideration",
        },
    )
    assert response.status_code == 201
    return response.json()


def add_strategy(
    db_session: Session, product_id: int, positioning: str
) -> MarketingStrategy:
    strategy = MarketingStrategy(
        product_id=product_id,
        positioning=positioning,
        audience_insights=["Commuters value portable routines."],
        angles=["Blend between meetings"],
        risks=["Avoid unsupported health claims."],
        evidence=["Portable design and USB charging."],
    )
    db_session.add(strategy)
    db_session.commit()
    db_session.refresh(strategy)
    return strategy


def platform_copy(platform: str) -> dict[str, object]:
    return {
        "platform": platform,
        "hook": f"  {platform} hook  ",
        "caption": f"  {platform} caption  ",
        "hashtags": [f"  #{platform}Ready  "],
        "cta": f"  Explore on {platform}  ",
    }


def provider_result(platforms: list[str]) -> str:
    return json.dumps({"copies": [platform_copy(item) for item in platforms]})


def task_copy_url(task_id: int, strategy_id: int) -> str:
    return (
        f"/api/v1/marketing-tasks/{task_id}"
        f"/strategies/{strategy_id}/copy"
    )


@pytest.mark.parametrize(
    "platforms",
    [["TikTok"], ["TikTok", "Instagram"]],
)
def test_task_bound_copy_uses_exact_sources_and_platform_snapshot(
    client: TestClient,
    db_session: Session,
    platforms: list[str],
) -> None:
    product = create_product(client, "Exact Copy Product")
    requested_task = create_task(client, product["id"], platforms)
    latest_task = create_task(client, product["id"], ["Facebook"])
    requested_strategy = add_strategy(
        db_session, product["id"], "Requested exact positioning"
    )
    latest_strategy = add_strategy(
        db_session, product["id"], "Latest strategy must not be selected"
    )
    product_row = requested_strategy.product
    product_row.target_markets = ["CA"]
    db_session.commit()

    provider = RecordingTaskCopyProvider(provider_result(platforms))
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            task_copy_url(requested_task["id"], requested_strategy.id)
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert latest_task["id"] > requested_task["id"]
    assert latest_strategy.id > requested_strategy.id
    assert response.status_code == 200
    body = response.json()
    assert body["source_task_id"] == requested_task["id"]
    assert body["source_strategy_id"] == requested_strategy.id
    assert body["source_product_id"] == product["id"]
    assert body["source_kind"] == "marketing_brief_and_strategy"
    assert body["requested_platforms"] == platforms
    assert body["strategy_association_persisted"] is True
    assert body["brief_association_persisted"] is False
    assert "no MarketingBrief foreign key" in body["association_notice"]
    assert body["copy_matrix"]["marketing_strategy_id"] == requested_strategy.id
    assert [
        copy["platform"] for copy in body["copy_matrix"]["copies"]
    ] == platforms
    assert all(
        copy["hook"] == copy["hook"].strip()
        and copy["caption"] == copy["caption"].strip()
        and copy["cta"] == copy["cta"].strip()
        and all(tag == tag.strip() for tag in copy["hashtags"])
        for copy in body["copy_matrix"]["copies"]
    )

    assert len(provider.prompts) == 1
    prompt = provider.prompts[0]
    input_data = json.loads(prompt.split("Execution input JSON:\n", 1)[1])
    assert input_data["product"] == {
        "id": product["id"],
        "name": "Exact Copy Product",
        "category": "Portable Kitchen Appliance",
        "description": "A portable blender for busy cross-border shoppers.",
        "selling_points": ["Portable design", "USB rechargeable"],
    }
    assert input_data["marketing_brief"]["id"] == requested_task["id"]
    assert input_data["marketing_brief"]["product_id"] == product["id"]
    assert input_data["marketing_brief"]["target_market_snapshot"] == ["US"]
    assert input_data["marketing_brief"]["platforms"] == platforms
    assert input_data["marketing_brief"]["audience"] == "Busy commuters"
    assert input_data["marketing_brief"]["language"] == "English"
    assert input_data["marketing_brief"]["tone"] == "Clear and energetic"
    assert input_data["marketing_brief"]["objective"] == (
        "Drive product consideration"
    )
    assert input_data["marketing_strategy"]["id"] == requested_strategy.id
    assert input_data["marketing_strategy"]["product_id"] == product["id"]
    assert input_data["marketing_strategy"]["positioning"] == (
        "Requested exact positioning"
    )
    assert input_data["marketing_strategy"]["audience_insights"]
    assert input_data["marketing_strategy"]["angles"]
    assert input_data["marketing_strategy"]["risks"]
    assert input_data["marketing_strategy"]["evidence"]

    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 1
    assert db_session.scalar(select(func.count(VideoProject.id))) == 0
    assert db_session.scalar(select(func.count(VideoRenderTask.id))) == 0
    assert db_session.scalar(select(func.count(VideoRenderArtifact.id))) == 0


def test_task_bound_copy_normalizes_provider_platform_names(
    client: TestClient,
    db_session: Session,
) -> None:
    product = create_product(client, "Normalization Product")
    task = create_task(client, product["id"], ["TikTok", "Instagram"])
    strategy = add_strategy(db_session, product["id"], "Normalized positioning")
    provider = RecordingTaskCopyProvider(
        provider_result(["  tiktok  ", "INSTAGRAM"])
    )
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(task_copy_url(task["id"], strategy.id))
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 200
    assert [
        item["platform"] for item in response.json()["copy_matrix"]["copies"]
    ] == ["TikTok", "Instagram"]


@pytest.mark.parametrize(
    ("task_platforms", "copies"),
    [
        (["TikTok", "Instagram"], [platform_copy("TikTok")]),
        (
            ["TikTok"],
            [platform_copy("TikTok"), platform_copy("Facebook")],
        ),
        (
            ["TikTok"],
            [platform_copy("TikTok"), platform_copy("TikTok")],
        ),
        (["TikTok"], [platform_copy("YouTube")]),
        (
            ["TikTok"],
            [{**platform_copy("TikTok"), "hook": " \t "}],
        ),
        (
            ["TikTok"],
            [{**platform_copy("TikTok"), "caption": "\n "}],
        ),
        (
            ["TikTok"],
            [{**platform_copy("TikTok"), "hashtags": ["  "]}],
        ),
        (
            ["TikTok"],
            [{**platform_copy("TikTok"), "cta": "   "}],
        ),
    ],
)
def test_invalid_task_bound_provider_output_is_not_saved(
    client: TestClient,
    db_session: Session,
    task_platforms: list[str],
    copies: list[dict[str, object]],
) -> None:
    product = create_product(client, "Invalid Output Product")
    task = create_task(client, product["id"], task_platforms)
    strategy = add_strategy(db_session, product["id"], "Valid positioning")
    provider = RecordingTaskCopyProvider(json.dumps({"copies": copies}))
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(task_copy_url(task["id"], strategy.id))
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 502
    assert response.json()["error"]["message"] in (
        "Qwen returned invalid copy data",
        "Qwen returned invalid copy platform data",
    )
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0
    assert db_session.scalar(select(func.count(VideoProject.id))) == 0


def test_task_bound_copy_rejects_cross_product_before_provider(
    client: TestClient,
    db_session: Session,
) -> None:
    first = create_product(client, "First Copy Product")
    second = create_product(client, "Second Copy Product")
    task = create_task(client, first["id"], ["TikTok"])
    strategy = add_strategy(db_session, second["id"], "Second positioning")
    provider = RecordingTaskCopyProvider(provider_result(["TikTok"]))
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(task_copy_url(task["id"], strategy.id))
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 409
    assert provider.prompts == []
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0


@pytest.mark.parametrize(
    ("provider_error", "status", "message"),
    [
        (
            ProviderAuthenticationError("private provider response"),
            502,
            "Qwen authentication failed",
        ),
        (
            ProviderConnectionError("private network details"),
            503,
            "Qwen service is unavailable",
        ),
        (
            ProviderQuotaError("private quota response"),
            429,
            "Qwen quota or rate limit reached",
        ),
        (
            ProviderModelError("private model response"),
            502,
            "Qwen generation failed",
        ),
    ],
)
def test_task_bound_provider_failures_are_safe_and_do_not_write(
    client: TestClient,
    db_session: Session,
    provider_error: Exception,
    status: int,
    message: str,
) -> None:
    product = create_product(client, "Safe Failure Product")
    task = create_task(client, product["id"], ["TikTok"])
    strategy = add_strategy(db_session, product["id"], "Safe positioning")
    provider = FailingTaskCopyProvider(provider_error)
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(task_copy_url(task["id"], strategy.id))
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == status
    assert response.json()["error"]["message"] == message
    assert "private" not in response.text.casefold()
    assert provider.calls == 1
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0


def test_task_bound_route_gate_stops_provider_resolution_and_write(
    client: TestClient,
    db_session: Session,
) -> None:
    product = create_product(client, "Closed Gate Product")
    task = create_task(client, product["id"], ["TikTok"])
    strategy = add_strategy(db_session, product["id"], "Valid positioning")
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Closed Copy gate must not resolve Provider")

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    try:
        response = client.post(task_copy_url(task["id"], strategy.id))
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 503
    assert provider_resolutions == 0
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0


def test_task_bound_service_gate_cannot_be_bypassed(
    db_session: Session,
) -> None:
    provider = RecordingTaskCopyProvider(provider_result(["TikTok"]))
    with pytest.raises(AppError, match="disabled by the server"):
        CopyGenerationService(
            db_session, provider, Settings(_env_file=None)
        ).generate_for_marketing_task(1, 1)
    assert provider.prompts == []
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0


def test_latest_copy_read_is_isolated_by_exact_strategy_and_read_only(
    client: TestClient,
    db_session: Session,
) -> None:
    product = create_product(client, "Recovery Product")
    task = create_task(client, product["id"], ["TikTok"])
    first_strategy = add_strategy(db_session, product["id"], "First positioning")
    second_strategy = add_strategy(db_session, product["id"], "Second positioning")
    provider = RecordingTaskCopyProvider(provider_result(["TikTok"]))
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        first_response = client.post(
            task_copy_url(task["id"], first_strategy.id)
        )
        second_response = client.post(
            task_copy_url(task["id"], first_strategy.id)
        )
        other_response = client.post(
            task_copy_url(task["id"], second_strategy.id)
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert other_response.status_code == 200
    count_before = db_session.scalar(select(func.count(CopyMatrix.id)))
    calls_before = len(provider.prompts)

    recovered = client.get(
        f"/api/v1/strategies/{first_strategy.id}/copy/latest"
    )
    missing_strategy = client.get("/api/v1/strategies/999/copy/latest")

    no_copy_strategy = add_strategy(
        db_session, product["id"], "No copy positioning"
    )
    missing_copy = client.get(
        f"/api/v1/strategies/{no_copy_strategy.id}/copy/latest"
    )

    assert recovered.status_code == 200
    assert recovered.json()["id"] == second_response.json()["copy_matrix"]["id"]
    assert recovered.json()["marketing_strategy_id"] == first_strategy.id
    assert recovered.json()["id"] != other_response.json()["copy_matrix"]["id"]
    assert missing_strategy.status_code == 404
    assert missing_copy.status_code == 404
    assert len(provider.prompts) == calls_before
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == count_before


def test_task_bound_prompt_builder_is_pure(
    client: TestClient,
    db_session: Session,
) -> None:
    product_data = create_product(client, "Pure Prompt Product")
    task_data = create_task(client, product_data["id"], ["Facebook"])
    strategy = add_strategy(db_session, product_data["id"], "Pure positioning")
    product = strategy.product
    task = db_session.get(MarketingBrief, task_data["id"])
    assert task is not None
    before = db_session.scalar(select(func.count(CopyMatrix.id)))

    prompt = CopyGenerationService.build_marketing_task_prompt(
        product, task, strategy, ["Facebook"]
    )

    assert '"id": ' + str(task.id) in prompt
    assert '"id": ' + str(strategy.id) in prompt
    assert '"Facebook"' in prompt
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == before
