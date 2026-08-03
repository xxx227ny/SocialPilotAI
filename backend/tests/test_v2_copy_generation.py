from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.main import app
from app.models import (
    AdCampaign,
    CopyMatrix,
    MarketingBrief,
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
from app.repositories.copy import CopyMatrixRepository
from app.schemas.copy import V2CopyExecutionRequest, V2CopySourceRequest
from app.schemas.growth import (
    GrowthRecommendationConstraints,
    compute_recommendation_digest,
)
from app.services.v2_copy_generation_service import V2CopyGenerationService
from app.services.v2_copy_preflight import V2CopyPreflightService


class ControlledV2CopyProvider(TextGenerationProvider):
    def __init__(
        self,
        output: dict[str, object] | str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.output = output if output is not None else valid_provider_output()
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


def enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        dashscope_api_key="safe-fake-test-key",
        enable_copy_execution=True,
        enable_v2_copy_execution=True,
    )


def valid_recommendation() -> dict[str, object]:
    return {
        "summary": "Test a clearer portable-use message.",
        "observations": [
            {
                "scope": "overall",
                "platform": None,
                "metric": "ctr",
                "direction": "test",
                "hypothesis": "A clearer opening may improve attention.",
            }
        ],
        "copy_constraints": [
            {
                "platform": "TikTok",
                "hook_direction": "Lead with portable use.",
                "message_angle": "Convenience during a busy routine.",
                "cta_direction": "Invite a controlled product test.",
                "must_preserve": ["USB rechargeable"],
                "must_avoid": ["Causal performance claims"],
            }
        ],
        "video_constraint": {
            "platform": "TikTok",
            "opening_hook_direction": "Show the use case immediately.",
            "visual_focus": "Portable blender in a real routine.",
            "pacing_direction": "Keep the opening concise.",
            "cta_direction": "Invite viewers to learn more.",
            "must_preserve": ["Product visibility"],
            "must_avoid": ["Guaranteed outcomes"],
        },
        "budget_guidance": "Keep budget unchanged during the test.",
    }


def valid_provider_output() -> dict[str, object]:
    return {
        "copies": [
            {
                "platform": "TikTok",
                "hook": "Fresh drinks can fit into a busy routine.",
                "caption": "A portable, USB-rechargeable option for daily use.",
                "hashtags": ["#PortableBlender", "#DailyRoutine"],
                "cta": "Explore how it fits your routine.",
            }
        ]
    }


def model_counts(session: Session) -> dict[str, int]:
    models = (
        Product,
        AdCampaign,
        MarketingBrief,
        MarketingStrategy,
        CopyMatrix,
        VideoProject,
        VideoRenderTask,
        VideoRenderArtifact,
    )
    return {
        model.__name__: int(
            session.scalar(select(func.count()).select_from(model)) or 0
        )
        for model in models
    }


def create_source(
    client: TestClient,
    session: Session,
    product_payload: dict[str, object],
    *,
    name: str = "V2 Copy Product",
) -> dict[str, object]:
    product = client.post(
        "/api/v1/products", json={**product_payload, "name": name}
    ).json()
    strategy = MarketingStrategy(
        product_id=product["id"],
        positioning="Portable daily-routine companion.",
        audience_insights=["Busy professionals value convenience."],
        angles=["Blend anywhere"],
        risks=["Avoid unsupported outcomes."],
        evidence=["Portable design", "USB rechargeable"],
    )
    session.add(strategy)
    session.flush()
    source_copy = CopyMatrix(
        product_id=product["id"],
        marketing_strategy_id=strategy.id,
        copies=[
            {
                "platform": platform,
                "hook": f"{platform} source hook",
                "caption": f"{platform} source caption",
                "hashtags": ["#Source"],
                "cta": "Learn more.",
            }
            for platform in ("TikTok", "Instagram", "Facebook")
        ],
    )
    session.add(source_copy)
    session.flush()
    project = VideoProject(
        product_id=product["id"],
        marketing_strategy_id=strategy.id,
        copy_matrix_id=source_copy.id,
        platform="TikTok",
        title="Portable routine",
        concept="Show a controlled product routine.",
        duration_seconds=10,
        aspect_ratio="9:16",
        scenes=[
            {
                "sequence": 1,
                "duration_seconds": 10,
                "shot_type": "Product",
                "visual_description": "Portable blender on a desk",
                "action": "Blend a drink",
                "narration": "Blend during a busy routine",
            }
        ],
        cta="Learn more",
        status="planned",
    )
    session.add(project)
    session.add(
        AdCampaign(
            product_id=product["id"],
            platform="TikTok",
            campaign_name="private-campaign-name",
            date=date(2026, 7, 29),
            impressions=1000,
            clicks=50,
            conversions=10,
            spend=Decimal("100"),
            revenue=Decimal("300"),
        )
    )
    session.commit()
    context = client.get(
        f"/api/v1/products/{product['id']}/feedback-context"
    ).json()
    recommendation = GrowthRecommendationConstraints.model_validate(
        valid_recommendation()
    )
    recommendation_digest = compute_recommendation_digest(
        product_id=product["id"],
        source_context_digest=context["context_digest"],
        source_marketing_strategy_id=strategy.id,
        source_copy_matrix_id=source_copy.id,
        source_video_project_id=project.id,
        recommendation=recommendation,
    )
    request = {
        "source_context_digest": context["context_digest"],
        "source_marketing_strategy_id": strategy.id,
        "source_copy_matrix_id": source_copy.id,
        "source_video_project_id": project.id,
        "recommendation_digest": recommendation_digest,
        "recommendation": recommendation.model_dump(mode="json"),
    }
    return {
        "product_id": product["id"],
        "strategy": strategy,
        "source_copy": source_copy,
        "project": project,
        "context": context,
        "request": request,
    }


def preflight(
    session: Session, source: dict[str, object]
) -> tuple[V2CopySourceRequest, str]:
    data = V2CopySourceRequest.model_validate(source["request"])
    result = V2CopyPreflightService(
        session, enabled_settings()
    ).run(int(source["product_id"]), data)
    assert result.ready_for_execution is True
    return data, result.preflight_digest


def request_for_platforms(
    source: dict[str, object], platforms: list[str]
) -> V2CopySourceRequest:
    request = deepcopy(source["request"])
    base = request["recommendation"]["copy_constraints"][0]
    request["recommendation"]["copy_constraints"] = [
        {
            **base,
            "platform": platform,
            "hook_direction": f"Lead with the {platform} routine.",
        }
        for platform in platforms
    ]
    recommendation = GrowthRecommendationConstraints.model_validate(
        request["recommendation"]
    )
    request["recommendation_digest"] = compute_recommendation_digest(
        product_id=int(source["product_id"]),
        source_context_digest=str(request["source_context_digest"]),
        source_marketing_strategy_id=int(
            request["source_marketing_strategy_id"]
        ),
        source_copy_matrix_id=int(request["source_copy_matrix_id"]),
        source_video_project_id=int(request["source_video_project_id"]),
        recommendation=recommendation,
    )
    return V2CopySourceRequest.model_validate(request)


def provider_output_for(platforms: list[str]) -> dict[str, object]:
    base = valid_provider_output()["copies"][0]
    return {
        "copies": [
            {
                **base,
                "platform": platform,
                "hook": f"{platform} controlled hook.",
            }
            for platform in platforms
        ]
    }


def test_recommendation_digest_is_stable_and_tracks_every_source_field() -> None:
    recommendation = GrowthRecommendationConstraints.model_validate(
        valid_recommendation()
    )
    values = {
        "product_id": 1,
        "source_context_digest": "a" * 64,
        "source_marketing_strategy_id": 2,
        "source_copy_matrix_id": 3,
        "source_video_project_id": 4,
        "recommendation": recommendation,
    }
    first = compute_recommendation_digest(**values)
    assert first == compute_recommendation_digest(**values)
    assert len(first) == 64 and first == first.lower()
    for field, replacement in (
        ("product_id", 9),
        ("source_context_digest", "b" * 64),
        ("source_marketing_strategy_id", 9),
        ("source_copy_matrix_id", 9),
        ("source_video_project_id", 9),
    ):
        changed = {**values, field: replacement}
        assert compute_recommendation_digest(**changed) != first
    changed_payload = deepcopy(valid_recommendation())
    changed_payload["summary"] = "Changed summary."
    assert compute_recommendation_digest(
        **{
            **values,
            "recommendation": GrowthRecommendationConstraints.model_validate(
                changed_payload
            ),
        }
    ) != first


def test_growth_response_digest_is_backend_owned(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    provider = ControlledV2CopyProvider(valid_recommendation())
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        dashscope_api_key="safe-fake-test-key",
        enable_growth_execution=True,
    )
    try:
        response = client.post(
            f"/api/v1/products/{source['product_id']}/growth-analysis",
            json={
                "expected_context_digest": source["context"]["context_digest"]
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["recommendation_digest"] == compute_recommendation_digest(
        product_id=body["product_id"],
        source_context_digest=body["source_context_digest"],
        source_marketing_strategy_id=body["source_marketing_strategy_id"],
        source_copy_matrix_id=body["source_copy_matrix_id"],
        source_video_project_id=body["source_video_project_id"],
        recommendation=GrowthRecommendationConstraints.model_validate(
            body["recommendation"]
        ),
    )
    assert body["recommendation_integrity_scope"] == (
        "deterministic_round_trip_not_authenticated"
    )


def test_preflight_is_provider_free_read_only_and_stable(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    before = model_counts(db_session)
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Preflight must not resolve a Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        path = f"/api/v1/products/{source['product_id']}/v2-copy/preflight"
        first = client.post(path, json=source["request"])
        second = client.post(path, json=source["request"])
    finally:
        app.dependency_overrides.clear()
    assert first.status_code == second.status_code == 200
    assert first.json()["preflight_digest"] == second.json()["preflight_digest"]
    assert first.json()["ready_for_execution"] is True
    assert first.json()["preflight_only"] is True
    assert first.json()["source_copy_platforms"] == [
        "TikTok",
        "Instagram",
        "Facebook",
    ]
    assert first.json()["allowed_copy_constraint_platforms"] == [
        "TikTok",
        "Instagram",
        "Facebook",
    ]
    assert first.json()["recommendation_target_copy_platforms"] == [
        "TikTok"
    ]
    assert first.json()["v2_copy_target_platforms"] == ["TikTok"]
    assert provider_resolutions == 0
    assert model_counts(db_session) == before


@pytest.mark.parametrize(
    ("mutation", "missing"),
    [
        (
            lambda data: data.update(source_context_digest="b" * 64),
            "stale_context_digest",
        ),
        (
            lambda data: data.update(recommendation_digest="b" * 64),
            "recommendation_digest_mismatch",
        ),
        (
            lambda data: data.update(source_copy_matrix_id=999),
            "source_content_chain_mismatch",
        ),
        (
            lambda data: data["recommendation"].update(
                copy_constraints=[
                    {
                        **data["recommendation"]["copy_constraints"][0],
                        "platform": "Instagram",
                    }
                ]
            ),
            "recommendation_digest_mismatch",
        ),
    ],
)
def test_preflight_blocks_stale_or_mismatched_identity(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    mutation: object,
    missing: str,
) -> None:
    source = create_source(client, db_session, product_payload)
    request = deepcopy(source["request"])
    mutation(request)  # type: ignore[operator]
    result = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(
        int(source["product_id"]),
        V2CopySourceRequest.model_validate(request),
    )
    assert result.ready_for_execution is False
    assert missing in result.missing_requirements


def test_preflight_missing_product_is_404(
    client: TestClient,
) -> None:
    request = {
        "source_context_digest": "a" * 64,
        "source_marketing_strategy_id": 1,
        "source_copy_matrix_id": 1,
        "source_video_project_id": 1,
        "recommendation_digest": "b" * 64,
        "recommendation": valid_recommendation(),
    }
    response = client.post("/api/v1/products/999/v2-copy/preflight", json=request)
    assert response.status_code == 404


def test_preflight_reports_both_default_off_gates(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    result = V2CopyPreflightService(
        db_session,
        Settings(_env_file=None, dashscope_api_key="safe-fake-test-key"),
    ).run(
        int(source["product_id"]),
        V2CopySourceRequest.model_validate(source["request"]),
    )
    assert result.input_ready is True
    assert result.copy_execution_enabled is False
    assert result.v2_copy_execution_enabled is False
    assert result.ready_for_execution is False
    assert {"copy_execution", "v2_copy_execution"}.issubset(
        result.missing_requirements
    )


def test_preflight_incomplete_context_is_blocked_and_provider_free(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = client.post("/api/v1/products", json=product_payload).json()["id"]
    before = model_counts(db_session)
    request = {
        "source_context_digest": "a" * 64,
        "source_marketing_strategy_id": 1,
        "source_copy_matrix_id": 1,
        "source_video_project_id": 1,
        "recommendation_digest": "b" * 64,
        "recommendation": valid_recommendation(),
    }
    result = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(product_id, V2CopySourceRequest.model_validate(request))
    assert result.input_ready is False
    assert result.ready_for_execution is False
    assert "campaign_data" in result.missing_requirements
    assert model_counts(db_session) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"name": None},
        {"name": ""},
        {"name": " \t\n "},
        {"category": None},
        {"category": ""},
        {"category": " \t\n "},
        {"description": None},
        {"description": ""},
        {"description": " \t\n "},
        {"selling_points": None},
        {"selling_points": []},
        {"selling_points": [None]},
        {"selling_points": [123]},
        {"selling_points": [" \t\n "]},
        {"selling_points": ["Portable design", None]},
    ],
)
def test_product_readiness_rejects_incomplete_values_without_exceptions(
    changes: dict[str, object],
) -> None:
    values = {
        "name": "Portable Blender",
        "category": "Portable Kitchen Appliance",
        "description": "A complete product description",
        "selling_points": ["Portable design", "USB rechargeable"],
        **changes,
    }
    product = SimpleNamespace(**values)
    assert V2CopyPreflightService._product_ready(product) is False  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "   "},
        {"category": None},
        {"category": "   "},
        {"description": "   "},
        {"selling_points": []},
        {"selling_points": [None]},
        {"selling_points": [123]},
        {"selling_points": [" \t\n "]},
        {"selling_points": ["Portable design", None]},
    ],
)
def test_preflight_invalid_persisted_product_is_safe_blocked(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    changes: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    db_session.execute(
        update(Product)
        .where(Product.id == int(source["product_id"]))
        .values(**changes)
    )
    db_session.commit()
    before = model_counts(db_session)
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Preflight must not resolve a Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        response = client.post(
            f"/api/v1/products/{source['product_id']}/v2-copy/preflight",
            json=source["request"],
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["input_ready"] is False
    assert body["ready_for_execution"] is False
    assert "product_input" in body["missing_requirements"]
    assert provider_resolutions == 0
    assert model_counts(db_session) == before
    assert "attributeerror" not in response.text.casefold()
    assert "typeerror" not in response.text.casefold()


def test_execution_with_incomplete_product_stops_before_provider_and_write(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    _, digest = preflight(db_session, source)
    db_session.execute(
        update(Product)
        .where(Product.id == int(source["product_id"]))
        .values(category=None)
    )
    db_session.commit()
    before = model_counts(db_session)
    provider = ControlledV2CopyProvider()
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        response = client.post(
            f"/api/v1/products/{source['product_id']}/v2-copy",
            json={
                **source["request"],
                "expected_preflight_digest": digest,
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409
    assert provider.calls == 0
    assert model_counts(db_session) == before
    assert "attributeerror" not in response.text.casefold()
    assert "typeerror" not in response.text.casefold()


def test_cross_product_source_ids_fail_closed(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    first = create_source(
        client, db_session, product_payload, name="Source Product A"
    )
    second = create_source(
        client, db_session, product_payload, name="Source Product B"
    )
    request = deepcopy(first["request"])
    request.update(
        source_marketing_strategy_id=second["strategy"].id,
        source_copy_matrix_id=second["source_copy"].id,
        source_video_project_id=second["project"].id,
    )
    recommendation = GrowthRecommendationConstraints.model_validate(
        request["recommendation"]
    )
    request["recommendation_digest"] = compute_recommendation_digest(
        product_id=int(first["product_id"]),
        source_context_digest=str(request["source_context_digest"]),
        source_marketing_strategy_id=int(
            request["source_marketing_strategy_id"]
        ),
        source_copy_matrix_id=int(request["source_copy_matrix_id"]),
        source_video_project_id=int(request["source_video_project_id"]),
        recommendation=recommendation,
    )
    result = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(
        int(first["product_id"]),
        V2CopySourceRequest.model_validate(request),
    )
    assert result.input_ready is False
    assert "source_content_chain_mismatch" in result.missing_requirements


def test_preflight_digest_changes_with_valid_recommendation_change(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    original = V2CopySourceRequest.model_validate(source["request"])
    first = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(int(source["product_id"]), original)
    request = deepcopy(source["request"])
    request["recommendation"]["summary"] = "A different valid test hypothesis."
    recommendation = GrowthRecommendationConstraints.model_validate(
        request["recommendation"]
    )
    request["recommendation_digest"] = compute_recommendation_digest(
        product_id=int(source["product_id"]),
        source_context_digest=str(request["source_context_digest"]),
        source_marketing_strategy_id=int(
            request["source_marketing_strategy_id"]
        ),
        source_copy_matrix_id=int(request["source_copy_matrix_id"]),
        source_video_project_id=int(request["source_video_project_id"]),
        recommendation=recommendation,
    )
    second = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(
        int(source["product_id"]),
        V2CopySourceRequest.model_validate(request),
    )
    assert first.ready_for_execution is second.ready_for_execution is True
    assert first.preflight_digest != second.preflight_digest


@pytest.mark.parametrize(
    "settings",
    [
        Settings(
            _env_file=None,
            dashscope_api_key="safe-fake-test-key",
            enable_copy_execution=False,
            enable_v2_copy_execution=True,
        ),
        Settings(
            _env_file=None,
            dashscope_api_key="safe-fake-test-key",
            enable_copy_execution=True,
            enable_v2_copy_execution=False,
        ),
    ],
)
def test_route_gate_blocks_before_provider_resolution(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    settings: Settings,
) -> None:
    source = create_source(client, db_session, product_payload)
    _, digest = preflight(db_session, source)
    request = {**source["request"], "expected_preflight_digest": digest}
    resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal resolutions
        resolutions += 1
        raise AssertionError("Disabled route resolved Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = client.post(
            f"/api/v1/products/{source['product_id']}/v2-copy",
            json=request,
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert resolutions == 0
    assert model_counts(db_session)["CopyMatrix"] == 1


def test_service_double_gate_cannot_be_bypassed(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    _, digest = preflight(db_session, source)
    data = V2CopyExecutionRequest.model_validate(
        {**source["request"], "expected_preflight_digest": digest}
    )
    provider = ControlledV2CopyProvider()
    with pytest.raises(AppError, match="disabled by the server"):
        V2CopyGenerationService(
            db_session,
            provider,
            Settings(
                _env_file=None,
                enable_copy_execution=True,
                enable_v2_copy_execution=False,
            ),
        ).generate(int(source["product_id"]), data)
    assert provider.calls == 0


def test_success_api_returns_backend_owned_candidate_contract(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    provider = ControlledV2CopyProvider()
    before = model_counts(db_session)
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        preflight_response = client.post(
            f"/api/v1/products/{source['product_id']}/v2-copy/preflight",
            json=source["request"],
        )
        response = client.post(
            f"/api/v1/products/{source['product_id']}/v2-copy",
            json={
                **source["request"],
                "expected_preflight_digest": preflight_response.json()[
                    "preflight_digest"
                ],
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert preflight_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert provider.calls == 1
    assert body["source_kind"] == "feedback_recommendation_constraints"
    assert body["generation_scope"] == "copy_only"
    assert body["provider_calls"] == 1
    assert body["source_copy_modified"] is False
    assert body["recommendation_persisted"] is False
    assert body["parent_relation_persisted"] is False
    assert body["version_label_persisted"] is False
    assert body["source_copy_platforms"] == [
        "TikTok",
        "Instagram",
        "Facebook",
    ]
    assert body["allowed_copy_constraint_platforms"] == [
        "TikTok",
        "Instagram",
        "Facebook",
    ]
    assert body["recommendation_target_copy_platforms"] == ["TikTok"]
    assert body["v2_copy_target_platforms"] == ["TikTok"]
    assert body["persisted_copy_platforms"] == ["TikTok"]
    assert body["preflight_digest"] == preflight_response.json()[
        "preflight_digest"
    ]
    assert body["copy_matrix_id"] == body["generated_copy_matrix"]["id"]
    assert model_counts(db_session)["CopyMatrix"] == before["CopyMatrix"] + 1


def test_success_calls_provider_once_and_only_adds_one_copy_matrix(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    data, digest = preflight(db_session, source)
    before = model_counts(db_session)
    source_copies = deepcopy(source["source_copy"].copies)
    provider = ControlledV2CopyProvider()
    result = V2CopyGenerationService(
        db_session, provider, enabled_settings()
    ).generate(
        int(source["product_id"]),
        V2CopyExecutionRequest.model_validate(
            {
                **data.model_dump(mode="json"),
                "expected_preflight_digest": digest,
            }
        ),
    )
    after = model_counts(db_session)
    assert provider.calls == 1
    assert after["CopyMatrix"] == before["CopyMatrix"] + 1
    for name in before:
        if name != "CopyMatrix":
            assert after[name] == before[name]
    assert result.generated_copy_matrix.product_id == source["product_id"]
    assert (
        result.generated_copy_matrix.marketing_strategy_id
        == source["strategy"].id
    )
    assert result.source_copy_matrix_id == source["source_copy"].id
    assert source["source_copy"].copies == source_copies
    assert result.copy_generation_triggered is True
    assert result.video_generation_triggered is False
    assert result.parent_relation_persisted is False


def test_prompt_contains_only_safe_business_inputs(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    data, digest = preflight(db_session, source)
    provider = ControlledV2CopyProvider()
    V2CopyGenerationService(
        db_session, provider, enabled_settings()
    ).generate(
        int(source["product_id"]),
        V2CopyExecutionRequest.model_validate(
            {
                **data.model_dump(mode="json"),
                "expected_preflight_digest": digest,
            }
        ),
    )
    prompt = provider.prompts[0]
    assert "target_platforms" in prompt
    assert "recommendation_copy_constraints" in prompt
    assert "private-campaign-name" not in prompt
    assert source["context"]["context_digest"] not in prompt
    assert '"product_id"' not in prompt
    assert '"source_context_digest"' not in prompt
    assert '"source_copy_matrix_id"' not in prompt
    assert "expected_preflight_digest" not in prompt
    assert "api_key" not in prompt.casefold()


def test_context_change_after_preflight_stops_before_provider(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    data, digest = preflight(db_session, source)
    campaign = db_session.scalar(
        select(AdCampaign).where(
            AdCampaign.product_id == int(source["product_id"])
        )
    )
    assert campaign is not None
    campaign.clicks += 1
    db_session.commit()
    provider = ControlledV2CopyProvider()
    with pytest.raises(AppError, match="not ready"):
        V2CopyGenerationService(
            db_session, provider, enabled_settings()
        ).generate(
            int(source["product_id"]),
            V2CopyExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": digest,
                }
            ),
        )
    assert provider.calls == 0


def test_provider_platform_order_must_match_recommendation_order(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    request = deepcopy(source["request"])
    instagram = {
        **request["recommendation"]["copy_constraints"][0],
        "platform": "Instagram",
        "hook_direction": "Lead with a visual routine.",
    }
    request["recommendation"]["copy_constraints"].append(instagram)
    recommendation = GrowthRecommendationConstraints.model_validate(
        request["recommendation"]
    )
    request["recommendation_digest"] = compute_recommendation_digest(
        product_id=int(source["product_id"]),
        source_context_digest=str(request["source_context_digest"]),
        source_marketing_strategy_id=int(
            request["source_marketing_strategy_id"]
        ),
        source_copy_matrix_id=int(request["source_copy_matrix_id"]),
        source_video_project_id=int(request["source_video_project_id"]),
        recommendation=recommendation,
    )
    data = V2CopySourceRequest.model_validate(request)
    preflight_result = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(int(source["product_id"]), data)
    assert preflight_result.target_platforms == ["TikTok", "Instagram"]
    output = valid_provider_output()["copies"][0]
    provider = ControlledV2CopyProvider(
        {
            "copies": [
                {**output, "platform": "Instagram"},
                output,
            ]
        }
    )
    before = model_counts(db_session)
    with pytest.raises(AppError, match="invalid V2 Copy data"):
        V2CopyGenerationService(
            db_session, provider, enabled_settings()
        ).generate(
            int(source["product_id"]),
            V2CopyExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": (
                        preflight_result.preflight_digest
                    ),
                }
            ),
        )
    assert provider.calls == 1
    assert model_counts(db_session) == before


def test_platform_evidence_scenario_a_single_target_succeeds(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    data = request_for_platforms(source, ["TikTok"])
    preflight_result = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(int(source["product_id"]), data)
    before = model_counts(db_session)
    provider = ControlledV2CopyProvider(provider_output_for(["TikTok"]))
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        response = client.post(
            f"/api/v1/products/{source['product_id']}/v2-copy",
            json={
                **data.model_dump(mode="json"),
                "expected_preflight_digest": preflight_result.preflight_digest,
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    result = response.json()
    assert preflight_result.source_copy_platforms == [
        "TikTok",
        "Instagram",
        "Facebook",
    ]
    assert preflight_result.allowed_copy_constraint_platforms == [
        "TikTok",
        "Instagram",
        "Facebook",
    ]
    assert preflight_result.recommendation_target_copy_platforms == ["TikTok"]
    assert preflight_result.v2_copy_target_platforms == ["TikTok"]
    assert result["persisted_copy_platforms"] == ["TikTok"]
    assert provider.calls == 1
    assert model_counts(db_session)["CopyMatrix"] == before["CopyMatrix"] + 1


def test_platform_evidence_scenario_b_three_targets_rejects_one_output(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    data = request_for_platforms(
        source, ["TikTok", "Instagram", "Facebook"]
    )
    preflight_result = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(int(source["product_id"]), data)
    before = model_counts(db_session)
    provider = ControlledV2CopyProvider(provider_output_for(["TikTok"]))
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        response = client.post(
            f"/api/v1/products/{source['product_id']}/v2-copy",
            json={
                **data.model_dump(mode="json"),
                "expected_preflight_digest": preflight_result.preflight_digest,
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 502
    assert preflight_result.v2_copy_target_platforms == [
        "TikTok",
        "Instagram",
        "Facebook",
    ]
    assert provider.calls == 1
    assert model_counts(db_session) == before


def test_platform_evidence_scenario_c_rejects_reversed_order(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    data = request_for_platforms(source, ["TikTok", "Instagram"])
    preflight_result = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(int(source["product_id"]), data)
    before = model_counts(db_session)
    provider = ControlledV2CopyProvider(
        provider_output_for(["Instagram", "TikTok"])
    )
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        response = client.post(
            f"/api/v1/products/{source['product_id']}/v2-copy",
            json={
                **data.model_dump(mode="json"),
                "expected_preflight_digest": preflight_result.preflight_digest,
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 502
    assert provider.calls == 1
    assert model_counts(db_session) == before


def test_platform_evidence_scenario_d_changed_target_stops_before_provider(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    three_platform_data = request_for_platforms(
        source, ["TikTok", "Instagram", "Facebook"]
    )
    three_platform_preflight = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(int(source["product_id"]), three_platform_data)
    one_platform_data = request_for_platforms(source, ["TikTok"])
    provider = ControlledV2CopyProvider()
    before = model_counts(db_session)
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        response = client.post(
            f"/api/v1/products/{source['product_id']}/v2-copy",
            json={
                **one_platform_data.model_dump(mode="json"),
                "expected_preflight_digest": (
                    three_platform_preflight.preflight_digest
                ),
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409
    assert provider.calls == 0
    assert model_counts(db_session) == before


@pytest.mark.parametrize(
    "output",
    [
        "not-json",
        {"copies": [], "extra": "forbidden"},
        {
            "copies": [
                {
                    **valid_provider_output()["copies"][0],
                    "platform": "Instagram",
                }
            ]
        },
        {
            "copies": [
                valid_provider_output()["copies"][0],
                valid_provider_output()["copies"][0],
            ]
        },
        {
            "copies": [
                {
                    **valid_provider_output()["copies"][0],
                    "hook": " ",
                }
            ]
        },
        {
            "copies": [
                {
                    **valid_provider_output()["copies"][0],
                    "caption": "x" * 1201,
                }
            ]
        },
        {
            "copies": [
                {
                    **valid_provider_output()["copies"][0],
                    "hashtags": ["#Same", " #same "],
                }
            ]
        },
    ],
)
def test_invalid_provider_output_never_writes(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    output: object,
) -> None:
    source = create_source(client, db_session, product_payload)
    data, digest = preflight(db_session, source)
    before = model_counts(db_session)
    provider = ControlledV2CopyProvider(output=output)  # type: ignore[arg-type]
    with pytest.raises(AppError, match="invalid V2 Copy data") as exc_info:
        V2CopyGenerationService(
            db_session, provider, enabled_settings()
        ).generate(
            int(source["product_id"]),
            V2CopyExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": digest,
                }
            ),
        )
    assert exc_info.value.status_code == 502
    assert provider.calls == 1
    assert model_counts(db_session) == before


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProviderAuthenticationError("private"), 502),
        (ProviderConnectionError("private"), 503),
        (ProviderQuotaError("private"), 503),
        (ProviderModelError("private"), 502),
    ],
)
def test_provider_failures_are_safe_and_write_nothing(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    error: Exception,
    status: int,
) -> None:
    source = create_source(client, db_session, product_payload)
    data, digest = preflight(db_session, source)
    before = model_counts(db_session)
    with pytest.raises(AppError) as exc_info:
        V2CopyGenerationService(
            db_session,
            ControlledV2CopyProvider(error=error),
            enabled_settings(),
        ).generate(
            int(source["product_id"]),
            V2CopyExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": digest,
                }
            ),
        )
    assert exc_info.value.status_code == status
    assert "private" not in exc_info.value.message
    assert model_counts(db_session) == before


def test_stale_expected_preflight_digest_stops_before_provider(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    data, _ = preflight(db_session, source)
    provider = ControlledV2CopyProvider()
    with pytest.raises(AppError, match="Preflight changed") as exc_info:
        V2CopyGenerationService(
            db_session, provider, enabled_settings()
        ).generate(
            int(source["product_id"]),
            V2CopyExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": "b" * 64,
                }
            ),
        )
    assert exc_info.value.status_code == 409
    assert provider.calls == 0


def test_persisted_platform_mismatch_rolls_back_without_false_success(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_source(client, db_session, product_payload)
    data = request_for_platforms(source, ["TikTok", "Instagram"])
    preflight_result = V2CopyPreflightService(
        db_session, enabled_settings()
    ).run(int(source["product_id"]), data)
    before = model_counts(db_session)
    original = CopyMatrixRepository.create_for_exact_strategy

    def return_inconsistent_platforms(
        repository: CopyMatrixRepository,
        product_id: int,
        marketing_strategy_id: int,
        copy_data: object,
        *,
        commit: bool = True,
    ) -> CopyMatrix:
        generated = original(
            repository,
            product_id,
            marketing_strategy_id,
            copy_data,  # type: ignore[arg-type]
            commit=commit,
        )
        generated.copies = [generated.copies[0]]
        return generated

    monkeypatch.setattr(
        CopyMatrixRepository,
        "create_for_exact_strategy",
        return_inconsistent_platforms,
    )
    provider = ControlledV2CopyProvider(
        provider_output_for(["TikTok", "Instagram"])
    )
    with pytest.raises(AppError, match="could not be saved") as exc_info:
        V2CopyGenerationService(
            db_session, provider, enabled_settings()
        ).generate(
            int(source["product_id"]),
            V2CopyExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": (
                        preflight_result.preflight_digest
                    ),
                }
            ),
        )
    assert exc_info.value.status_code == 500
    assert provider.calls == 1
    assert model_counts(db_session) == before


def test_commit_failure_rolls_back_without_false_success(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_source(client, db_session, product_payload)
    data, digest = preflight(db_session, source)
    before = model_counts(db_session)

    def fail_commit() -> None:
        raise RuntimeError("private database failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(AppError, match="could not be saved") as exc_info:
        V2CopyGenerationService(
            db_session,
            ControlledV2CopyProvider(),
            enabled_settings(),
        ).generate(
            int(source["product_id"]),
            V2CopyExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": digest,
                }
            ),
        )
    assert exc_info.value.status_code == 500
    assert model_counts(db_session) == before
