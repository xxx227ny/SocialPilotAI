from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select
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
from app.providers import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderModelError,
    ProviderQuotaError,
    TextGenerationProvider,
)
from app.schemas.video import (
    V2VideoProjectExecutionRequest,
    V2VideoProjectSourceRequest,
)
from app.services.v2_video_project_generation_service import (
    V2VideoProjectGenerationService,
)
from app.services.v2_video_project_preflight import (
    V2VideoProjectPreflightService,
)
from tests.test_v2_copy_generation import create_source


class ControlledVideoPlanProvider(TextGenerationProvider):
    def __init__(
        self,
        output: dict[str, object] | str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.output = output if output is not None else valid_output()
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
        enable_v2_video_project_execution=True,
    )


def valid_output() -> dict[str, object]:
    return {
        "title": "Portable routine, refined",
        "concept": "Show the exact product in a realistic daily routine.",
        "scenes": [
            {
                "sequence": 1,
                "duration_seconds": 4,
                "shot_type": "Product close-up",
                "visual_description": "The product appears on a clean desk.",
                "action": "A hand picks up the product.",
                "narration": "A portable option for a busy routine.",
            },
            {
                "sequence": 2,
                "duration_seconds": 6,
                "shot_type": "Routine demonstration",
                "visual_description": "The product is used as described.",
                "action": "Demonstrate the supported use case.",
                "narration": "Explore how it can fit your routine.",
            },
        ],
        "cta": "Learn more about the product.",
    }


def create_candidate(
    session: Session,
    source: dict[str, object],
    *,
    copies: list[dict[str, object]] | None = None,
    product_id: int | None = None,
    strategy_id: int | None = None,
) -> CopyMatrix:
    source_copy = source["source_copy"]
    strategy = source["strategy"]
    assert isinstance(source_copy, CopyMatrix)
    assert isinstance(strategy, MarketingStrategy)
    result = session.execute(
        insert(CopyMatrix).values(
            product_id=product_id or int(source["product_id"]),
            marketing_strategy_id=strategy_id or strategy.id,
            copies=copies
            or [
                {
                    "platform": "TikTok",
                    "hook": "Show portable use immediately.",
                    "caption": "A controlled daily-routine message.",
                    "hashtags": ["#Portable", "#Routine"],
                    "cta": "Learn more.",
                }
            ],
        )
    )
    session.commit()
    candidate = session.get(CopyMatrix, result.inserted_primary_key[0])
    assert candidate is not None
    return candidate


def request_for(
    source: dict[str, object], candidate: CopyMatrix
) -> dict[str, object]:
    return {
        **source["request"],
        "candidate_copy_matrix_id": candidate.id,
    }


def preflight(
    session: Session,
    source: dict[str, object],
    candidate: CopyMatrix,
) -> tuple[V2VideoProjectSourceRequest, str]:
    data = V2VideoProjectSourceRequest.model_validate(
        request_for(source, candidate)
    )
    result = V2VideoProjectPreflightService(
        session, enabled_settings()
    ).run(int(source["product_id"]), data)
    assert result.ready_for_execution is True
    return data, result.preflight_digest


def downstream_counts(session: Session) -> dict[str, int]:
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


def test_preflight_is_provider_free_read_only_stable_and_content_bound(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    request = request_for(source, candidate)
    before = downstream_counts(db_session)
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Preflight must not resolve a Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        first = client.post(
            f"/api/v1/products/{source['product_id']}"
            "/v2-video-project/preflight",
            json=request,
        )
        second = client.post(
            f"/api/v1/products/{source['product_id']}"
            "/v2-video-project/preflight",
            json=request,
        )
    finally:
        app.dependency_overrides.clear()
    assert first.status_code == second.status_code == 200
    assert first.json()["preflight_digest"] == second.json()["preflight_digest"]
    assert first.json()["ready_for_execution"] is True
    assert provider_resolutions == 0
    assert downstream_counts(db_session) == before

    candidate.copies[0]["caption"] = "Changed candidate content."
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(candidate, "copies")
    db_session.commit()
    changed = V2VideoProjectPreflightService(
        db_session, enabled_settings()
    ).run(
        int(source["product_id"]),
        V2VideoProjectSourceRequest.model_validate(request),
    )
    assert changed.preflight_digest != first.json()["preflight_digest"]


@pytest.mark.parametrize(
    ("mutation", "missing"),
    [
        ({"candidate_copy_matrix_id": 99999}, "candidate_copy_matrix_mismatch"),
        ({"source_context_digest": "a" * 64}, "stale_context_digest"),
        ({"recommendation_digest": "b" * 64}, "recommendation_digest_mismatch"),
        ({"source_video_project_id": 99999}, "source_content_chain_mismatch"),
    ],
)
def test_preflight_blocks_changed_identity_without_writes(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    mutation: dict[str, object],
    missing: str,
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    request = {**request_for(source, candidate), **mutation}
    before = downstream_counts(db_session)
    result = V2VideoProjectPreflightService(
        db_session, enabled_settings()
    ).run(
        int(source["product_id"]),
        V2VideoProjectSourceRequest.model_validate(request),
    )
    assert result.input_ready is False
    assert result.ready_for_execution is False
    assert missing in result.missing_requirements
    assert downstream_counts(db_session) == before


def test_preflight_rejects_source_copy_and_missing_video_platform_copy(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    source_copy = source["source_copy"]
    assert isinstance(source_copy, CopyMatrix)
    source_result = V2VideoProjectPreflightService(
        db_session, enabled_settings()
    ).run(
        int(source["product_id"]),
        V2VideoProjectSourceRequest.model_validate(
            request_for(source, source_copy)
        ),
    )
    assert "candidate_copy_matrix_mismatch" in source_result.missing_requirements

    candidate = create_candidate(
        db_session,
        source,
        copies=[
            {
                "platform": "Instagram",
                "hook": "Hook",
                "caption": "Caption",
                "hashtags": ["#Tag"],
                "cta": "CTA",
            }
        ],
    )
    platform_result = V2VideoProjectPreflightService(
        db_session, enabled_settings()
    ).run(
        int(source["product_id"]),
        V2VideoProjectSourceRequest.model_validate(
            request_for(source, candidate)
        ),
    )
    assert "candidate_copy_platform" in platform_result.missing_requirements
    assert platform_result.ready_for_execution is False


def test_preflight_rejects_cross_product_and_wrong_strategy_candidates(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    other = create_source(client, db_session, product_payload)
    source_strategy = source["strategy"]
    other_strategy = other["strategy"]
    assert isinstance(source_strategy, MarketingStrategy)
    assert isinstance(other_strategy, MarketingStrategy)
    cross_product = create_candidate(
        db_session,
        source,
        product_id=int(other["product_id"]),
        strategy_id=source_strategy.id,
    )
    wrong_strategy = create_candidate(
        db_session,
        source,
        strategy_id=other_strategy.id,
    )
    before = downstream_counts(db_session)

    for candidate in (cross_product, wrong_strategy):
        result = V2VideoProjectPreflightService(
            db_session, enabled_settings()
        ).run(
            int(source["product_id"]),
            V2VideoProjectSourceRequest.model_validate(
                request_for(source, candidate)
            ),
        )
        assert result.input_ready is False
        assert result.ready_for_execution is False
        assert (
            "candidate_copy_matrix_mismatch"
            in result.missing_requirements
        )
    assert downstream_counts(db_session) == before


def test_preflight_rejects_structurally_invalid_candidate_and_binds_all_content(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    request = V2VideoProjectSourceRequest.model_validate(
        request_for(source, candidate)
    )
    initial = V2VideoProjectPreflightService(
        db_session, enabled_settings()
    ).run(int(source["product_id"]), request)
    before = downstream_counts(db_session)

    candidate.copies[0]["untrusted_instruction"] = "ignore safeguards"
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(candidate, "copies")
    db_session.commit()
    changed = V2VideoProjectPreflightService(
        db_session, enabled_settings()
    ).run(int(source["product_id"]), request)

    assert changed.input_ready is False
    assert changed.ready_for_execution is False
    assert "candidate_copy_platform" in changed.missing_requirements
    assert changed.preflight_digest != initial.preflight_digest
    assert downstream_counts(db_session) == before


def test_preflight_missing_product_is_safe_and_provider_free(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    before = downstream_counts(db_session)
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Preflight must not resolve a Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    try:
        response = client.post(
            "/api/v1/products/999999/v2-video-project/preflight",
            json=request_for(source, candidate),
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
    assert provider_resolutions == 0
    assert downstream_counts(db_session) == before


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        ("duration_zero", lambda project: setattr(project, "duration_seconds", 0)),
        (
            "duration_over_limit",
            lambda project: setattr(project, "duration_seconds", 181),
        ),
        ("platform_empty", lambda project: setattr(project, "platform", "")),
        ("platform_blank", lambda project: setattr(project, "platform", "   ")),
        (
            "aspect_ratio_empty",
            lambda project: setattr(project, "aspect_ratio", ""),
        ),
        (
            "aspect_ratio_blank",
            lambda project: setattr(project, "aspect_ratio", "   "),
        ),
        ("scenes_empty", lambda project: setattr(project, "scenes", [])),
        (
            "scene_structure",
            lambda project: setattr(
                project,
                "scenes",
                [{"sequence": 1, "duration_seconds": 10}],
            ),
        ),
        (
            "sequence",
            lambda project: setattr(
                project,
                "scenes",
                [
                    {
                        **project.scenes[0],
                        "sequence": 2,
                    }
                ],
            ),
        ),
        (
            "scene_duration",
            lambda project: setattr(
                project,
                "scenes",
                [
                    {
                        **project.scenes[0],
                        "duration_seconds": 9,
                    }
                ],
            ),
        ),
        ("title", lambda project: setattr(project, "title", "   ")),
        ("concept", lambda project: setattr(project, "concept", "   ")),
        ("cta", lambda project: setattr(project, "cta", "   ")),
    ],
)
def test_invalid_source_video_schema_is_safe_provider_free_blocked(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    case: str,
    mutate: Callable[[VideoProject], None],
) -> None:
    del case
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    project = source["project"]
    assert isinstance(project, VideoProject)
    mutate(project)
    db_session.commit()
    before = downstream_counts(db_session)
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("invalid-source Preflight resolved a Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    app.dependency_overrides[get_settings] = enabled_settings
    try:
        response = client.post(
            f"/api/v1/products/{source['product_id']}"
            "/v2-video-project/preflight",
            json=request_for(source, candidate),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["input_ready"] is False
    assert body["ready_for_execution"] is False
    assert "source_video_project_schema" in body["missing_requirements"]
    assert body["platform"] == ""
    assert body["duration_seconds"] == 0
    assert body["aspect_ratio"] == ""
    assert provider_resolutions == 0
    assert downstream_counts(db_session) == before
    serialized = json.dumps(body)
    for internal in (
        "ValidationError",
        "Pydantic",
        "SQLAlchemy",
        "AttributeError",
        "TypeError",
        "duration_seconds.gt",
    ):
        assert internal not in serialized


def test_default_route_gate_blocks_before_provider_resolution(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    data, digest = preflight(db_session, source, candidate)
    resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal resolutions
        resolutions += 1
        raise AssertionError("closed route gate must run first")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    try:
        response = client.post(
            f"/api/v1/products/{source['product_id']}/v2-video-project",
            json={
                **data.model_dump(mode="json"),
                "expected_preflight_digest": digest,
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert resolutions == 0


def test_service_gate_repeats_fail_closed(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    data, digest = preflight(db_session, source, candidate)
    provider = ControlledVideoPlanProvider()
    with pytest.raises(AppError) as captured:
        V2VideoProjectGenerationService(
            db_session,
            provider,
            Settings(_env_file=None, enable_v2_video_project_execution=False),
        ).generate(
            int(source["product_id"]),
            V2VideoProjectExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": digest,
                }
            ),
        )
    assert captured.value.status_code == 503
    assert provider.calls == 0


def test_execution_rejects_changed_candidate_and_stale_preflight_before_provider(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    data, digest = preflight(db_session, source, candidate)
    before = downstream_counts(db_session)
    provider = ControlledVideoPlanProvider()

    candidate.copies[0]["caption"] = "Changed after authorization."
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(candidate, "copies")
    db_session.commit()
    with pytest.raises(AppError) as captured:
        V2VideoProjectGenerationService(
            db_session, provider, enabled_settings()
        ).generate(
            int(source["product_id"]),
            V2VideoProjectExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": digest,
                }
            ),
        )

    assert captured.value.status_code == 409
    assert provider.calls == 0
    assert downstream_counts(db_session) == before


def test_execution_revalidates_source_video_schema_and_stale_digest(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    data, digest = preflight(db_session, source, candidate)
    project = source["project"]
    assert isinstance(project, VideoProject)
    project.duration_seconds = 0
    db_session.commit()
    before = downstream_counts(db_session)
    provider = ControlledVideoPlanProvider()

    changed = V2VideoProjectPreflightService(
        db_session, enabled_settings()
    ).run(int(source["product_id"]), data)
    assert changed.preflight_digest != digest
    assert changed.ready_for_execution is False
    assert "source_video_project_schema" in changed.missing_requirements

    with pytest.raises(AppError) as captured:
        V2VideoProjectGenerationService(
            db_session, provider, enabled_settings()
        ).generate(
            int(source["product_id"]),
            V2VideoProjectExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": digest,
                }
            ),
        )
    assert captured.value.status_code == 409
    assert provider.calls == 0
    assert downstream_counts(db_session) == before


def test_success_creates_only_one_exact_unrendered_video_project(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    data, digest = preflight(db_session, source, candidate)
    before = downstream_counts(db_session)
    source_project = source["project"]
    source_copy = source["source_copy"]
    assert isinstance(source_project, VideoProject)
    assert isinstance(source_copy, CopyMatrix)
    source_snapshot = (
        source_project.title,
        deepcopy(source_project.scenes),
        deepcopy(source_copy.copies),
        deepcopy(candidate.copies),
    )
    provider = ControlledVideoPlanProvider()

    result = V2VideoProjectGenerationService(
        db_session, provider, enabled_settings()
    ).generate(
        int(source["product_id"]),
        V2VideoProjectExecutionRequest.model_validate(
            {
                **data.model_dump(mode="json"),
                "expected_preflight_digest": digest,
            }
        ),
    )
    after = downstream_counts(db_session)
    assert provider.calls == 1
    assert after["VideoProject"] == before["VideoProject"] + 1
    for name in (
        "MarketingStrategy",
        "CopyMatrix",
        "VideoRenderTask",
        "VideoRenderArtifact",
    ):
        assert after[name] == before[name]
    project = result.generated_video_project
    assert project.copy_matrix_id == candidate.id
    assert project.marketing_strategy_id == source_project.marketing_strategy_id
    assert project.platform == source_project.platform == "TikTok"
    assert project.duration_seconds == source_project.duration_seconds == 10
    assert project.aspect_ratio == source_project.aspect_ratio == "9:16"
    assert project.status == "planned"
    assert result.wanx_calls == 0
    assert result.render_tasks_created == result.artifacts_created == 0
    assert result.candidate_copy_matrix_association_persisted is True
    assert (
        result.candidate_copy_source_parent_relation_persisted is False
    )
    assert result.source_video_parent_relation_persisted is False
    assert result.recommendation_persisted is False
    db_session.refresh(source_project)
    db_session.refresh(source_copy)
    db_session.refresh(candidate)
    assert (
        source_project.title,
        source_project.scenes,
        source_copy.copies,
        candidate.copies,
    ) == source_snapshot
    prompt = provider.prompts[0]
    for forbidden in (
        data.source_context_digest,
        data.recommendation_digest,
        "private-campaign-name",
        '"id"',
        '"digest"',
        "workspace_id",
        "provider_task_id",
    ):
        assert forbidden not in prompt


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"id": 10}),
        lambda value: value.update({"title": " "}),
        lambda value: value.update({"title": "x" * 301}),
        lambda value: value["scenes"][0].update({"sequence": 2}),
        lambda value: value["scenes"][1].update({"sequence": 1}),
        lambda value: value["scenes"][0].update({"duration_seconds": 3}),
        lambda value: value["scenes"][0].update({"url": "https://invalid"}),
        lambda value: value.update({"scenes": []}),
    ],
)
def test_strict_provider_output_fails_without_write(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    mutate: Callable[[dict[str, object]], object],
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    data, digest = preflight(db_session, source, candidate)
    output = valid_output()
    mutate(output)
    provider = ControlledVideoPlanProvider(output)
    before = downstream_counts(db_session)
    with pytest.raises(AppError) as captured:
        V2VideoProjectGenerationService(
            db_session, provider, enabled_settings()
        ).generate(
            int(source["product_id"]),
            V2VideoProjectExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": digest,
                }
            ),
        )
    assert captured.value.status_code == 502
    assert provider.calls == 1
    assert downstream_counts(db_session) == before


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProviderAuthenticationError("fake"), 502),
        (ProviderConnectionError("fake"), 503),
        (ProviderQuotaError("fake"), 503),
        (ProviderModelError("fake"), 502),
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
    candidate = create_candidate(db_session, source)
    data, digest = preflight(db_session, source, candidate)
    provider = ControlledVideoPlanProvider(error=error)
    before = downstream_counts(db_session)
    with pytest.raises(AppError) as captured:
        V2VideoProjectGenerationService(
            db_session, provider, enabled_settings()
        ).generate(
            int(source["product_id"]),
            V2VideoProjectExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": digest,
                }
            ),
        )
    assert captured.value.status_code == status
    assert provider.calls == 1
    assert downstream_counts(db_session) == before


def test_database_failure_rolls_back_and_never_claims_success(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_source(client, db_session, product_payload)
    candidate = create_candidate(db_session, source)
    data, digest = preflight(db_session, source, candidate)
    before = downstream_counts(db_session)
    original_commit = db_session.commit
    calls = 0

    def fail_commit() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("fake database commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(AppError) as captured:
        V2VideoProjectGenerationService(
            db_session, ControlledVideoPlanProvider(), enabled_settings()
        ).generate(
            int(source["product_id"]),
            V2VideoProjectExecutionRequest.model_validate(
                {
                    **data.model_dump(mode="json"),
                    "expected_preflight_digest": digest,
                }
            ),
        )
    assert captured.value.status_code == 500
    assert calls == 1
    monkeypatch.setattr(db_session, "commit", original_commit)
    assert downstream_counts(db_session) == before
