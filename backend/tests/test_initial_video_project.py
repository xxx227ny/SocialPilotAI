import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_text_generation_provider
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.main import app
from app.models import CopyMatrix, MarketingStrategy, Product, VideoProject
from app.providers.base import TextGenerationProvider
from app.schemas.video import (
    InitialVideoProjectExecutionRequest,
    InitialVideoProjectSourceRequest,
)
from app.services.initial_video_project_generation_service import (
    InitialVideoProjectGenerationService,
)
from app.services.initial_video_project_preflight import (
    InitialVideoProjectPreflightService,
)
from tests.test_content_studio_service import add_video_sources, valid_plan


class FakeInitialVideoProvider(TextGenerationProvider):
    def __init__(self, result: dict[str, object] | None = None) -> None:
        self.result = result or valid_plan()
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        assert "structured short-video production plan" in prompt
        return json.dumps(self.result)


def enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        qwen_api_key="safe-initial-video-key",
        dashscope_api_key=None,
        enable_video_project_execution=True,
    )


def source_payload(
    strategy: MarketingStrategy,
    copy_matrix: CopyMatrix,
) -> dict[str, object]:
    return {
        "strategy_id": strategy.id,
        "copy_matrix_id": copy_matrix.id,
        "platform": "TikTok",
        "duration_seconds": 30,
        "aspect_ratio": "9:16",
    }


def preflight(
    client: TestClient,
    product: Product,
    strategy: MarketingStrategy,
    copy_matrix: CopyMatrix,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/products/{product.id}/video-projects/preflight",
        json=source_payload(strategy, copy_matrix),
    )
    assert response.status_code == 200
    return response.json()


def execution_payload(
    strategy: MarketingStrategy,
    copy_matrix: CopyMatrix,
    preflight_data: dict[str, object],
) -> dict[str, object]:
    return {
        **source_payload(strategy, copy_matrix),
        "expected_preflight_digest": preflight_data["preflight_digest"],
        "preflight_expires_at": preflight_data["expires_at"],
        "confirm_cost": True,
    }


def test_preflight_is_provider_free_read_only_and_exact(
    client: TestClient,
    db_session: Session,
) -> None:
    product, strategy, copy_matrix = add_video_sources(db_session)
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Preflight must not resolve a Provider")

    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    before = db_session.scalar(select(func.count(VideoProject.id)))
    data = preflight(client, product, strategy, copy_matrix)
    after = db_session.scalar(select(func.count(VideoProject.id)))

    assert data["product_id"] == product.id
    assert data["strategy_id"] == strategy.id
    assert data["copy_matrix_id"] == copy_matrix.id
    assert data["provider_configured"] is True
    assert data["input_ready"] is True
    assert data["execution_enabled"] is True
    assert data["contract_ready"] is True
    assert data["ready_for_execution"] is True
    assert data["missing_requirements"] == []
    assert data["provider_calls"] == 0
    assert data["database_writes"] == 0
    assert len(data["preflight_digest"]) == 64
    assert datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")) > (
        datetime.now(UTC)
    )
    assert provider_resolutions == 0
    assert before == after == 0
    assert "safe-initial-video-key" not in json.dumps(data)


def test_source_query_selects_latest_valid_copy_chain_not_latest_strategy(
    client: TestClient,
    db_session: Session,
) -> None:
    product, strategy_with_copy, first_copy = add_video_sources(db_session)
    latest_valid_copy = CopyMatrix(
        product_id=product.id,
        marketing_strategy_id=strategy_with_copy.id,
        copies=first_copy.copies,
    )
    db_session.add(latest_valid_copy)
    db_session.commit()
    db_session.refresh(latest_valid_copy)

    latest_strategy_without_copy = MarketingStrategy(
        product_id=product.id,
        positioning="A newer strategy without generated copy",
        audience_insights=["New audience"],
        angles=["New angle"],
        risks=["New risk"],
        evidence=["New evidence"],
    )
    db_session.add(latest_strategy_without_copy)
    db_session.commit()
    db_session.refresh(latest_strategy_without_copy)

    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Source discovery must not resolve a Provider")

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    before = {
        model.__name__: db_session.scalar(select(func.count(model.id)))
        for model in (Product, MarketingStrategy, CopyMatrix, VideoProject)
    }

    response = client.get(
        f"/api/v1/products/{product.id}/video-projects/source"
    )

    after = {
        model.__name__: db_session.scalar(select(func.count(model.id)))
        for model in (Product, MarketingStrategy, CopyMatrix, VideoProject)
    }
    assert response.status_code == 200
    assert response.json() == {
        "product_id": product.id,
        "strategy_id": strategy_with_copy.id,
        "copy_matrix_id": latest_valid_copy.id,
        "selected_by": "latest_valid_copy_matrix",
        "provider_calls": 0,
        "database_writes": 0,
    }
    assert latest_strategy_without_copy.id > strategy_with_copy.id
    assert latest_valid_copy.id > first_copy.id
    assert before == after
    assert provider_resolutions == 0


def test_default_gate_blocks_before_provider_resolution(
    client: TestClient,
    db_session: Session,
) -> None:
    product, _, _ = add_video_sources(db_session)
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Gate must block before Provider resolution")

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    response = client.post(
        f"/api/v1/products/{product.id}/video-projects",
        json={"platform": "TikTok", "duration_seconds": 30, "aspect_ratio": "9:16"},
    )

    assert response.status_code == 503
    assert provider_resolutions == 0
    assert db_session.scalar(select(func.count(VideoProject.id))) == 0


def test_preflight_blocks_missing_provider_and_wrong_identity(
    client: TestClient,
    db_session: Session,
) -> None:
    first, first_strategy, first_copy = add_video_sources(db_session)
    second = Product(
        name="Second Product",
        category="Category",
        description="Complete description",
        selling_points=["One point"],
        target_markets=["US"],
    )
    db_session.add(second)
    db_session.commit()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        qwen_api_key=None,
        dashscope_api_key=None,
        enable_video_project_execution=True,
    )

    missing_provider = preflight(client, first, first_strategy, first_copy)
    mismatch = client.post(
        f"/api/v1/products/{second.id}/video-projects/preflight",
        json=source_payload(first_strategy, first_copy),
    )

    assert missing_provider["provider_configured"] is False
    assert missing_provider["ready_for_execution"] is False
    assert "provider_configuration" in missing_provider["missing_requirements"]
    assert mismatch.status_code == 200
    assert mismatch.json()["input_ready"] is False
    assert "source_association" in mismatch.json()["missing_requirements"]


def test_execution_rejects_digest_cost_and_expiry_before_provider(
    client: TestClient,
    db_session: Session,
) -> None:
    product, strategy, copy_matrix = add_video_sources(db_session)
    provider = FakeInitialVideoProvider()
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    data = preflight(client, product, strategy, copy_matrix)
    payload = execution_payload(strategy, copy_matrix, data)

    wrong_digest = client.post(
        f"/api/v1/products/{product.id}/video-projects/execute",
        json={**payload, "expected_preflight_digest": "0" * 64},
    )
    no_cost = client.post(
        f"/api/v1/products/{product.id}/video-projects/execute",
        json={**payload, "confirm_cost": False},
    )
    expired = client.post(
        f"/api/v1/products/{product.id}/video-projects/execute",
        json={
            **payload,
            "preflight_expires_at": (
                datetime.now(UTC) - timedelta(seconds=1)
            ).isoformat(),
        },
    )

    assert wrong_digest.status_code == 409
    assert no_cost.status_code == 422
    assert expired.status_code == 409
    assert provider.calls == 0
    assert db_session.scalar(select(func.count(VideoProject.id))) == 0


def test_invalid_schema_does_not_create_video_project(
    client: TestClient,
    db_session: Session,
) -> None:
    product, strategy, copy_matrix = add_video_sources(db_session)
    invalid = valid_plan()
    invalid["scenes"] = []
    provider = FakeInitialVideoProvider(invalid)
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    data = preflight(client, product, strategy, copy_matrix)

    response = client.post(
        f"/api/v1/products/{product.id}/video-projects/execute",
        json=execution_payload(strategy, copy_matrix, data),
    )

    assert response.status_code == 502
    assert provider.calls == 1
    assert db_session.scalar(select(func.count(VideoProject.id))) == 0


def test_success_and_immediate_duplicate_reuse_exact_project(
    client: TestClient,
    db_session: Session,
) -> None:
    product, strategy, copy_matrix = add_video_sources(db_session)
    provider = FakeInitialVideoProvider()
    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    data = preflight(client, product, strategy, copy_matrix)
    payload = execution_payload(strategy, copy_matrix, data)

    first = client.post(
        f"/api/v1/products/{product.id}/video-projects/execute",
        json=payload,
    )
    second = client.post(
        f"/api/v1/products/{product.id}/video-projects/execute",
        json=payload,
    )

    assert first.status_code == second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["reused"] is False
    assert first_body["provider_calls"] == 1
    assert second_body["reused"] is True
    assert second_body["provider_calls"] == 0
    assert (
        first_body["generated_video_project"]["id"]
        == second_body["generated_video_project"]["id"]
    )
    assert first_body["strategy_id"] == strategy.id
    assert first_body["copy_matrix_id"] == copy_matrix.id
    assert provider.calls == 1
    assert db_session.scalar(select(func.count(VideoProject.id))) == 1


def test_concurrent_double_click_calls_provider_once(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'double-click.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = enabled_settings()
    with sessions() as setup:
        product, strategy, copy_matrix = add_video_sources(setup)
        source = InitialVideoProjectSourceRequest(
            **source_payload(strategy, copy_matrix)
        )
        checked = InitialVideoProjectPreflightService(
            setup, settings
        ).run(product.id, source)
        execution = InitialVideoProjectExecutionRequest(
            **source.model_dump(),
            expected_preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            confirm_cost=True,
        )
        product_id = product.id

    provider = FakeInitialVideoProvider()

    def execute_once() -> tuple[int, bool, int]:
        with sessions() as session:
            result = InitialVideoProjectGenerationService(
                session, provider, settings
            ).generate(product_id, execution)
            return (
                result.generated_video_project.id,
                result.reused,
                result.provider_calls,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: execute_once(), range(2)))

    with sessions() as check:
        assert check.scalar(select(func.count(VideoProject.id))) == 1
    assert provider.calls == 1
    assert results[0][0] == results[1][0]
    assert sorted((item[1], item[2]) for item in results) == [
        (False, 1),
        (True, 0),
    ]
    Base.metadata.drop_all(engine)
    engine.dispose()
