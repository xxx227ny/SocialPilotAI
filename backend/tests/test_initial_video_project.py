import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    CopyMatrix,
    ExecutionJob,
    MarketingStrategy,
    Product,
    VideoProject,
)
from app.providers.base import TextGenerationProvider
from tests.test_content_studio_service import add_video_sources


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
    product: Product,
    strategy: MarketingStrategy,
    copy_matrix: CopyMatrix,
    preflight_data: dict[str, object],
) -> dict[str, object]:
    return {
        **source_payload(strategy, copy_matrix),
        "product_id": product.id,
        "input_digest": preflight_data["input_digest"],
        "preflight_digest": preflight_data["preflight_digest"],
        "preflight_expires_at": preflight_data["expires_at"],
        "cost_confirmed": True,
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
    assert len(data["input_digest"]) == 64
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
    app.dependency_overrides[get_settings] = enabled_settings
    data = preflight(client, product, strategy, copy_matrix)
    payload = execution_payload(product, strategy, copy_matrix, data)

    wrong_digest = client.post(
        f"/api/v1/products/{product.id}/video-projects/execute",
        json={**payload, "preflight_digest": "0" * 64},
    )
    no_cost = client.post(
        f"/api/v1/products/{product.id}/video-projects/execute",
        json={**payload, "cost_confirmed": False},
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
    assert db_session.scalar(select(func.count(VideoProject.id))) == 0
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 0


def test_http_enqueue_is_provider_free_and_duplicate_reuses_exact_job(
    client: TestClient,
    db_session: Session,
) -> None:
    product, strategy, copy_matrix = add_video_sources(db_session)
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("HTTP enqueue must not resolve a Provider")

    app.dependency_overrides[get_settings] = enabled_settings
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    data = preflight(client, product, strategy, copy_matrix)
    payload = execution_payload(product, strategy, copy_matrix, data)

    first = client.post(
        f"/api/v1/products/{product.id}/video-projects/execute",
        json=payload,
    )
    second = client.post(
        f"/api/v1/products/{product.id}/video-projects/execute",
        json=payload,
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert provider_resolutions == 0
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 1
    assert db_session.scalar(select(func.count(VideoProject.id))) == 0
