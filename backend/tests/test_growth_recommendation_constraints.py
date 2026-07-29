from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.main import app
from app.models import (
    AdCampaign,
    CopyMatrix,
    MarketingStrategy,
    Product,
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
from app.schemas.growth import GrowthRecommendationConstraints
from app.services.growth_analysis_service import GrowthAnalysisService


class ControlledGrowthProvider(TextGenerationProvider):
    def __init__(
        self,
        output: dict[str, object] | str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.output = output if output is not None else valid_recommendation()
        self.error = error
        self.calls = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        if isinstance(self.output, str):
            return self.output
        return json.dumps(self.output)


def valid_recommendation() -> dict[str, object]:
    return {
        "summary": "Test clearer product framing without causal claims.",
        "observations": [
            {
                "scope": "overall",
                "platform": None,
                "metric": "ctr",
                "direction": "test",
                "hypothesis": "A clearer opening may improve attention.",
            },
            {
                "scope": "platform",
                "platform": " tiktok ",
                "metric": "conversion_rate",
                "direction": "investigate",
                "hypothesis": "Test whether message clarity affects intent.",
            },
        ],
        "copy_constraints": [
            {
                "platform": " tiktok ",
                "hook_direction": " Lead with portable use. ",
                "message_angle": "Convenience during a busy routine.",
                "cta_direction": "Invite a controlled product test.",
                "must_preserve": [" USB rechargeable "],
                "must_avoid": ["Causal performance claims"],
            }
        ],
        "video_constraint": {
            "platform": " tiktok ",
            "opening_hook_direction": "Show the use case immediately.",
            "visual_focus": "Portable blender in a real routine.",
            "pacing_direction": "Keep the opening concise.",
            "cta_direction": "Invite viewers to learn more.",
            "must_preserve": ["Product visibility"],
            "must_avoid": ["Guaranteed outcomes"],
        },
        "budget_guidance": "Keep budget unchanged during the test.",
    }


def model_counts(session: Session) -> dict[str, int]:
    return {
        model.__name__: int(
            session.scalar(select(func.count()).select_from(model)) or 0
        )
        for model in (
            Product,
            AdCampaign,
            MarketingStrategy,
            CopyMatrix,
            VideoProject,
            VideoRenderTask,
            VideoRenderArtifact,
        )
    }


def create_ready_context(
    client: TestClient,
    session: Session,
    product_payload: dict[str, object],
    *,
    name: str = "Growth Contract Product",
) -> dict[str, int | str]:
    product_id = client.post(
        "/api/v1/products", json={**product_payload, "name": name}
    ).json()["id"]
    strategy = MarketingStrategy(
        product_id=product_id,
        positioning="Portable routine companion.",
        audience_insights=["Busy professionals value convenience."],
        angles=["Blend anywhere"],
        risks=["Avoid causal or health guarantees."],
        evidence=["USB rechargeable"],
    )
    session.add(strategy)
    session.flush()
    copy_matrix = CopyMatrix(
        product_id=product_id,
        marketing_strategy_id=strategy.id,
        copies=[
            {
                "platform": platform,
                "hook": "Hook",
                "caption": "Caption",
                "hashtags": ["#Safe"],
                "cta": "CTA",
            }
            for platform in ("TikTok", "Instagram", "Facebook")
        ],
    )
    session.add(copy_matrix)
    session.flush()
    video_project = VideoProject(
        product_id=product_id,
        marketing_strategy_id=strategy.id,
        copy_matrix_id=copy_matrix.id,
        platform="TikTok",
        title="Portable routine",
        concept="Show a controlled use case.",
        duration_seconds=10,
        aspect_ratio="9:16",
        scenes=[
            {
                "sequence": 1,
                "duration_seconds": 10,
                "shot_type": "Product",
                "visual_description": "Portable blender",
                "action": "Blend a drink",
                "narration": "Blend anywhere",
            }
        ],
        cta="Learn more",
        status="planned",
    )
    session.add(video_project)
    session.add(
        AdCampaign(
            product_id=product_id,
            platform="TikTok",
            campaign_name="private-name",
            date=date(2026, 7, 29),
            impressions=1000,
            clicks=50,
            conversions=10,
            spend=Decimal("100"),
            revenue=Decimal("300"),
        )
    )
    session.commit()
    digest = client.get(
        f"/api/v1/products/{product_id}/feedback-context"
    ).json()["context_digest"]
    return {
        "product_id": product_id,
        "strategy_id": strategy.id,
        "copy_matrix_id": copy_matrix.id,
        "video_project_id": video_project.id,
        "digest": digest,
    }


def enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_growth_execution=True,
        dashscope_api_key="fake-test-key",
    )


def test_growth_preflight_missing_product_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/products/999/growth-analysis/preflight")
    assert response.status_code == 404


def test_growth_preflight_empty_context_is_blocked_and_provider_free(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = client.post(
        "/api/v1/products", json=product_payload
    ).json()["id"]
    provider_resolutions = 0
    before = model_counts(db_session)

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Preflight resolved a Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    try:
        response = client.get(
            f"/api/v1/products/{product_id}/growth-analysis/preflight"
        )
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 200
    body = response.json()
    assert body["input_ready"] is False
    assert body["ready_for_execution"] is False
    assert body["preflight_only"] is True
    assert body["execution_will_call_ai"] is True
    assert body["execution_will_write_database"] is False
    assert body["marketing_strategy_id"] is None
    assert body["copy_matrix_id"] is None
    assert body["video_project_id"] is None
    assert provider_resolutions == 0
    assert model_counts(db_session) == before


def test_growth_preflight_ready_and_blocked_gate_states(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    path = (
        f"/api/v1/products/{identity['product_id']}"
        "/growth-analysis/preflight"
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        dashscope_api_key="fake-test-key",
    )
    try:
        blocked = client.get(path)
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert blocked.status_code == 200
    assert blocked.json()["input_ready"] is True
    assert blocked.json()["provider_configured"] is True
    assert blocked.json()["execution_enabled"] is False
    assert blocked.json()["ready_for_execution"] is False
    assert "growth_execution" in blocked.json()["missing_requirements"]

    app.dependency_overrides[get_settings] = enabled_settings
    try:
        ready = client.get(path)
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert ready.status_code == 200
    body = ready.json()
    assert body["ready_for_execution"] is True
    assert body["contract_ready"] is True
    assert body["missing_requirements"] == []
    assert body["context_digest"] == identity["digest"]
    assert body["marketing_strategy_id"] == identity["strategy_id"]
    assert body["copy_matrix_id"] == identity["copy_matrix_id"]
    assert body["video_project_id"] == identity["video_project_id"]
    serialized = ready.text.casefold()
    for forbidden in ("api_key", "token", "authorization", "prompt", "c:\\"):
        assert forbidden not in serialized


def test_growth_preflight_cross_product_chain_is_atomically_blocked(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    left = create_ready_context(
        client, db_session, product_payload, name="Left Product"
    )
    right = create_ready_context(
        client, db_session, product_payload, name="Right Product"
    )
    left_project = db_session.get(VideoProject, left["video_project_id"])
    assert left_project is not None
    left_project.copy_matrix_id = int(right["copy_matrix_id"])
    db_session.commit()

    response = client.get(
        f"/api/v1/products/{left['product_id']}/growth-analysis/preflight"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["input_ready"] is False
    assert body["ready_for_execution"] is False
    assert body["marketing_strategy_id"] is None
    assert body["copy_matrix_id"] is None
    assert body["video_project_id"] is None
    assert "exact_content_chain" in body["missing_requirements"]


def test_growth_route_default_gate_blocks_before_provider_resolution(
    client: TestClient,
    product_payload: dict[str, object],
) -> None:
    product_id = client.post(
        "/api/v1/products", json=product_payload
    ).json()["id"]
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("disabled route resolved Provider")

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    try:
        response = client.post(
            f"/api/v1/products/{product_id}/growth-analysis",
            json={"expected_context_digest": "0" * 64},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 503
    assert provider_resolutions == 0


def test_growth_digest_mismatch_and_change_call_provider_zero_times(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    provider = ControlledGrowthProvider()
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        stale = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": "0" * 64},
        )
        campaign = db_session.scalar(
            select(AdCampaign).where(
                AdCampaign.product_id == identity["product_id"]
            )
        )
        assert campaign is not None
        campaign.clicks += 1
        db_session.commit()
        changed = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert stale.status_code == 409
    assert changed.status_code == 409
    assert provider.calls == 0
    assert "read Context and Preflight again" in stale.json()["error"]["message"]


def test_growth_request_rejects_invalid_digest_format_before_generation(
    client: TestClient,
    product_payload: dict[str, object],
) -> None:
    product_id = client.post(
        "/api/v1/products", json=product_payload
    ).json()["id"]
    provider = ControlledGrowthProvider()
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{product_id}/growth-analysis",
            json={"expected_context_digest": "not-a-digest"},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 422
    assert provider.calls == 0


def test_growth_execution_revalidates_reference_platforms_before_provider(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    db_session.execute(
        update(CopyMatrix)
        .where(CopyMatrix.id == identity["copy_matrix_id"])
        .values(
            copies=[
                {
                    "platform": "TikTok",
                    "hook": "First",
                    "caption": "First",
                    "hashtags": ["#First"],
                    "cta": "First",
                },
                {
                    "platform": "tiktok",
                    "hook": "Duplicate",
                    "caption": "Duplicate",
                    "hashtags": ["#Duplicate"],
                    "cta": "Duplicate",
                },
            ]
        )
    )
    db_session.commit()
    provider = ControlledGrowthProvider()
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 409
    assert provider.calls == 0
    assert (
        response.json()["error"]["message"]
        == "FeedbackContext reference platforms changed; "
        "read Context and Preflight again"
    )


def test_growth_success_calls_fake_once_and_writes_nothing(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    before = model_counts(db_session)
    provider = ControlledGrowthProvider()
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 200
    body = response.json()
    assert provider.calls == 1
    assert model_counts(db_session) == before
    assert body["product_id"] == identity["product_id"]
    assert body["source_context_digest"] == identity["digest"]
    assert body["source_marketing_strategy_id"] == identity["strategy_id"]
    assert body["source_copy_matrix_id"] == identity["copy_matrix_id"]
    assert body["source_video_project_id"] == identity["video_project_id"]
    assert body["provider_calls"] == 1
    assert body["recommendation_only"] is True
    assert body["recommendation_persisted"] is False
    assert body["causal_attribution_allowed"] is False
    assert body["automatic_action_allowed"] is False
    assert body["budget_change_allowed"] is False
    assert body["copy_generation_triggered"] is False
    assert body["video_generation_triggered"] is False
    assert body["recommendation"]["copy_constraints"][0]["platform"] == "TikTok"
    assert (
        body["recommendation"]["copy_constraints"][0]["must_preserve"]
        == ["USB rechargeable"]
    )
    prompt = provider.prompts[0]
    assert "campaign_name" not in prompt
    assert "private-name" not in prompt
    assert "expected_context_digest" not in prompt
    assert str(identity["digest"]) not in prompt
    assert '"ctr":0.05' in prompt
    assert "do not prove" in prompt


def test_mixed_supported_and_unrelated_campaign_platforms_execute_consistently(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    original_digest = identity["digest"]
    db_session.add(
        AdCampaign(
            product_id=identity["product_id"],
            platform="Google Ads",
            campaign_name="unrelated-channel",
            date=date(2026, 7, 30),
            impressions=500,
            clicks=20,
            conversions=2,
            spend=Decimal("50"),
            revenue=Decimal("100"),
        )
    )
    db_session.commit()
    context = client.get(
        f"/api/v1/products/{identity['product_id']}/feedback-context"
    ).json()
    before = model_counts(db_session)
    provider = ControlledGrowthProvider()
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        preflight = client.get(
            f"/api/v1/products/{identity['product_id']}"
            "/growth-analysis/preflight"
        )
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": context["context_digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert context["context_digest"] != original_digest
    assert context["campaign_count"] == 2
    assert context["overall_metrics"]["impressions"] == 1500
    assert {item["platform"] for item in context["platform_metrics"]} == {
        "Google Ads",
        "TikTok",
    }
    assert preflight.status_code == 200
    assert preflight.json()["ready_for_execution"] is True
    assert response.status_code == 200
    assert provider.calls == 1
    assert model_counts(db_session) == before
    prompt = provider.prompts[0]
    assert '"allowed_observation_platforms":["TikTok"]' in prompt
    assert (
        '"allowed_copy_constraint_platforms":'
        '["Facebook","Instagram","TikTok"]'
    ) in prompt
    assert '"required_video_constraint_platform":"TikTok"' in prompt
    assert '"impressions":1500' in prompt
    assert '"platform":"Google Ads"' not in prompt
    assert '"platform":"TikTok"' in prompt


def test_unrelated_only_campaign_allows_overall_only_recommendation(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    campaign = db_session.scalar(
        select(AdCampaign).where(
            AdCampaign.product_id == identity["product_id"]
        )
    )
    assert campaign is not None
    campaign.platform = "Google Ads"
    db_session.commit()
    context = client.get(
        f"/api/v1/products/{identity['product_id']}/feedback-context"
    ).json()
    payload = valid_recommendation()
    observations = payload["observations"]
    assert isinstance(observations, list)
    payload["observations"] = [observations[0]]
    provider = ControlledGrowthProvider(output=payload)
    before = model_counts(db_session)
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        preflight = client.get(
            f"/api/v1/products/{identity['product_id']}"
            "/growth-analysis/preflight"
        )
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": context["context_digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert preflight.json()["ready_for_execution"] is True
    assert response.status_code == 200
    assert provider.calls == 1
    assert model_counts(db_session) == before
    prompt = provider.prompts[0]
    assert '"allowed_observation_platforms":[]' in prompt
    assert '"platform_metrics":[]' in prompt
    assert '"required_video_constraint_platform":"TikTok"' in prompt
    assert '"platform":"Google Ads"' not in prompt


def test_unrelated_campaign_platform_observation_is_rejected_safely(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    campaign = db_session.scalar(
        select(AdCampaign).where(
            AdCampaign.product_id == identity["product_id"]
        )
    )
    assert campaign is not None
    campaign.platform = "Google Ads"
    db_session.commit()
    context = client.get(
        f"/api/v1/products/{identity['product_id']}/feedback-context"
    ).json()
    payload = valid_recommendation()
    payload["observations"] = [
        {
            "scope": "platform",
            "platform": "Google Ads",
            "metric": "ctr",
            "direction": "test",
            "hypothesis": "This unsupported scope must be rejected.",
        }
    ]
    provider = ControlledGrowthProvider(output=payload)
    before = model_counts(db_session)
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": context["context_digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Qwen returned invalid recommendation data"
    )
    assert provider.calls == 1
    assert model_counts(db_session) == before
    serialized = response.text.casefold()
    assert "google ads" not in serialized
    assert "traceback" not in serialized


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update({"extra": "forbidden"}),
        lambda value: value.update({"summary": "   "}),
        lambda value: value.update({"summary": "x" * 401}),
        lambda value: value.update({"observations": []}),
        lambda value: value.update(
            {"observations": value["observations"] * 5}
        ),
        lambda value: value["copy_constraints"].append(
            deepcopy(value["copy_constraints"][0])
        ),
        lambda value: value["copy_constraints"][0].update(
            {"platform": "YouTube"}
        ),
        lambda value: value["video_constraint"].update(
            {"product_id": 999}
        ),
        lambda value: value.update({"automatic_action_allowed": True}),
        lambda value: value["copy_constraints"][0].update(
            {"must_preserve": []}
        ),
    ],
)
def test_strict_growth_schema_rejects_invalid_provider_output(
    mutator,
) -> None:
    payload = valid_recommendation()
    mutator(payload)
    with pytest.raises(ValidationError):
        GrowthRecommendationConstraints.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        ("video_platform", "Instagram"),
        ("observation_platform", "Facebook"),
    ],
)
def test_dynamic_platform_mismatch_is_safe_and_writes_nothing(
    mutation: tuple[str, str],
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    payload = valid_recommendation()
    if mutation[0] == "video_platform":
        payload["video_constraint"]["platform"] = mutation[1]  # type: ignore[index]
    else:
        payload["observations"][1]["platform"] = mutation[1]  # type: ignore[index]
    provider = ControlledGrowthProvider(payload)
    before = model_counts(db_session)
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Qwen returned invalid recommendation data"
    )
    assert provider.calls == 1
    assert model_counts(db_session) == before


@pytest.mark.parametrize(
    ("error", "status_code", "safe_message"),
    [
        (
            ProviderAuthenticationError("raw credential detail"),
            502,
            "Qwen authentication failed",
        ),
        (
            ProviderConnectionError("raw connection detail"),
            503,
            "Qwen service is unavailable",
        ),
        (
            ProviderQuotaError("raw quota detail"),
            503,
            "Qwen quota or rate limit prevents execution",
        ),
        (
            ProviderModelError("raw model response"),
            502,
            "Qwen generation failed",
        ),
    ],
)
def test_provider_failures_are_safe_and_never_write(
    error: Exception,
    status_code: int,
    safe_message: str,
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    provider = ControlledGrowthProvider(error=error)
    before = model_counts(db_session)
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == status_code
    assert response.json()["error"]["message"] == safe_message
    assert "raw" not in response.text.casefold()
    assert provider.calls == 1
    assert model_counts(db_session) == before


@pytest.mark.parametrize("raw_output", ["not-json", "{}", '{"summary": 1}'])
def test_invalid_json_or_shape_is_safe_and_never_persisted(
    raw_output: str,
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    provider = ControlledGrowthProvider(raw_output)
    before = model_counts(db_session)
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Qwen returned invalid recommendation data"
    )
    assert model_counts(db_session) == before


def test_growth_service_gate_and_provider_configuration_cannot_be_bypassed(
    db_session: Session,
) -> None:
    provider = ControlledGrowthProvider()
    with pytest.raises(AppError) as disabled:
        GrowthAnalysisService(
            db_session, provider, Settings(_env_file=None)
        ).analyze(999, "0" * 64)
    assert disabled.value.status_code == 503
    assert provider.calls == 0

    with pytest.raises(AppError) as unconfigured:
        GrowthAnalysisService(
            db_session,
            provider,
            Settings(_env_file=None, enable_growth_execution=True),
        ).analyze(999, "0" * 64)
    assert unconfigured.value.status_code == 503
    assert provider.calls == 0
