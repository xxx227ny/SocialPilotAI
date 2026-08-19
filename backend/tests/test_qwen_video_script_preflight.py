from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.main import app
from app.models import (
    BatchVideoVariant,
    ExecutionAttempt,
    ExecutionJob,
    MarketingStrategy,
    Product,
    VideoScriptVersion,
    VideoStoryboardSceneVersion,
)
from app.schemas.video_script_version import (
    QwenScriptJobCreateRequest,
    QwenScriptPreflightRequest,
)
from app.services.qwen_video_script_job_service import QwenVideoScriptJobService
from app.services.qwen_video_script_preflight import QwenVideoScriptPreflightService
from tests.test_video_script_preflight import ready_variant


def qwen_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "enable_qwen_video_script_generation": True,
        "qwen_video_script_cost_min": Decimal("0.02"),
        "qwen_video_script_cost_max": Decimal("0.08"),
        "qwen_video_script_cost_currency": "CNY",
        "qwen_video_script_cost_basis": "test-budget-envelope-v1",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def strategy_for(session, product_id: int) -> MarketingStrategy:
    strategy = MarketingStrategy(
        product_id=product_id,
        positioning="Exact position",
        audience_insights=["Exact audience"],
        angles=["Proof"],
        risks=["No unsupported claims"],
        evidence=["Product record"],
    )
    session.add(strategy)
    session.commit()
    return strategy


def generation_state(session, variant_id: int) -> tuple[object, ...]:
    session.expire_all()
    variant = session.get(BatchVideoVariant, variant_id)
    assert variant is not None
    return (
        session.query(ExecutionJob).count(),
        session.query(ExecutionAttempt).count(),
        session.query(VideoScriptVersion).count(),
        session.query(VideoStoryboardSceneVersion).count(),
        variant.script_version_sequence,
        variant.active_script_version_id,
        variant.batch.qwen_script_calls_reserved,
    )


def request_for(
    strategy_id: int, key: str = "qwen-script-request-1"
) -> QwenScriptPreflightRequest:
    return QwenScriptPreflightRequest(
        idempotency_key=key,
        strategy_id=strategy_id,
        copy_matrix_id=None,
        parent_version_id=None,
    )


def create_from(checked, request, **overrides: object) -> QwenScriptJobCreateRequest:
    value = {
        **request.model_dump(),
        "frozen_input_digest": checked.frozen_input_digest,
        "preflight_digest": checked.preflight_digest,
        "preflight_expires_at": checked.expires_at,
        "estimated_cost_min": checked.estimated_cost_min,
        "estimated_cost_max": checked.estimated_cost_max,
        "currency": checked.currency,
        "cost_estimate_basis": checked.cost_estimate_basis,
        "cost_confirmed": True,
    }
    value.update(overrides)
    return QwenScriptJobCreateRequest.model_validate(value)


def test_preflight_is_provider_free_zero_write_and_cost_is_honest(db_session) -> None:
    variant = ready_variant(db_session)
    strategy = strategy_for(db_session, variant.product_id)
    before = generation_state(db_session, variant.id)
    checked = QwenVideoScriptPreflightService(db_session, qwen_settings()).run(
        variant.id, request_for(strategy.id)
    )
    assert generation_state(db_session, variant.id) == before
    assert checked.ready_for_execution is True
    assert (checked.estimated_cost_min, checked.estimated_cost_max) == (
        Decimal("0.02"),
        Decimal("0.08"),
    )
    assert checked.currency == "CNY"
    assert checked.provider_call_count == checked.database_writes == 0
    assert checked.estimated_provider_calls == 1
    assert checked.will_auto_activate is False
    unavailable = QwenVideoScriptPreflightService(
        db_session,
        qwen_settings(
            qwen_video_script_cost_min=None,
            qwen_video_script_cost_max=None,
            qwen_video_script_cost_basis=None,
        ),
    ).run(variant.id, request_for(strategy.id, "qwen-cost-unavailable"))
    assert unavailable.ready_for_execution is False
    assert unavailable.estimated_cost_min is unavailable.estimated_cost_max is None
    assert generation_state(db_session, variant.id) == before


@pytest.mark.parametrize(
    "case",
    ["expired", "digest", "cost", "product", "brand", "parent", "not-ready"],
)
def test_stale_tampered_or_invalid_confirmation_is_seven_way_zero_write(
    db_session, case
) -> None:
    variant = ready_variant(db_session)
    strategy = strategy_for(db_session, variant.product_id)
    request = request_for(strategy.id, f"qwen-invalid-{case}")
    checked = QwenVideoScriptPreflightService(db_session, qwen_settings()).run(
        variant.id, request
    )
    overrides: dict[str, object] = {}
    if case == "expired":
        overrides["preflight_expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    elif case == "digest":
        overrides["preflight_digest"] = "0" * 64
    elif case == "cost":
        overrides["estimated_cost_max"] = Decimal("0.09")
    elif case == "product":
        product = db_session.get(Product, variant.product_id)
        assert product is not None
        product.description = "Changed"
        db_session.commit()
    elif case == "brand":
        variant.brand_kit_version_digest = "f" * 64
        db_session.commit()
    elif case == "parent":
        overrides["parent_version_id"] = 999999
    elif case == "not-ready":
        variant.result_entity_type = None
        variant.result_entity_id = None
        variant.status = "PAUSED"
        db_session.commit()
    before = generation_state(db_session, variant.id)
    with pytest.raises(AppError):
        QwenVideoScriptJobService(db_session, qwen_settings()).enqueue(
            variant.id, create_from(checked, request, **overrides)
        )
    assert generation_state(db_session, variant.id) == before


def test_backend_feature_gate_is_default_closed(db_session) -> None:
    variant = ready_variant(db_session)
    strategy = strategy_for(db_session, variant.product_id)
    with pytest.raises(AppError) as failure:
        QwenVideoScriptPreflightService(db_session, Settings(_env_file=None)).run(
            variant.id, request_for(strategy.id)
        )
    assert failure.value.status_code == 404


def test_qwen_script_api_preflight_enqueue_exact_job_and_safe_errors(
    client, db_session
) -> None:
    settings = qwen_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    variant = ready_variant(db_session)
    strategy = strategy_for(db_session, variant.product_id)
    request = request_for(strategy.id, "qwen-api-exact")
    before = generation_state(db_session, variant.id)
    checked_response = client.post(
        f"/api/v1/batch-video-variants/{variant.id}/qwen-script/preflight",
        json=request.model_dump(mode="json"),
    )
    assert checked_response.status_code == 200
    assert generation_state(db_session, variant.id) == before
    checked = checked_response.json()
    assert checked["provider_call_count"] == checked["database_writes"] == 0
    created_response = client.post(
        f"/api/v1/batch-video-variants/{variant.id}/qwen-script/jobs",
        json={
            **request.model_dump(mode="json"),
            "frozen_input_digest": checked["frozen_input_digest"],
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
            "estimated_cost_min": checked["estimated_cost_min"],
            "estimated_cost_max": checked["estimated_cost_max"],
            "currency": checked["currency"],
            "cost_estimate_basis": checked["cost_estimate_basis"],
            "cost_confirmed": True,
        },
    )
    assert created_response.status_code == 201
    job = created_response.json()["job"]
    assert job["job_type"] == "qwen.video_script.generate.v1"
    assert job["source_id"] == variant.id
    assert job["attempt_count"] == 0 and job["max_attempts"] == 1
    exact = client.get(f"/api/v1/execution-jobs/{job['id']}")
    assert exact.status_code == 200 and exact.json()["id"] == job["id"]
    direct = client.post(
        "/api/v1/execution-jobs",
        json={
            "job_type": "qwen.video_script.generate.v1",
            "source_type": "batch_video_variant",
            "source_id": variant.id,
            "input_digest": "a" * 64,
            "idempotency_key": "forbidden-direct-job",
        },
    )
    assert direct.status_code == 409
    for path, payload in (
        (
            "/api/v1/batch-video-variants/999999/qwen-script/preflight",
            request.model_dump(mode="json"),
        ),
        (
            "/api/v1/batch-video-variants/999999/qwen-script/jobs",
            {
                **request.model_dump(mode="json"),
                "frozen_input_digest": checked["frozen_input_digest"],
                "preflight_digest": checked["preflight_digest"],
                "preflight_expires_at": checked["expires_at"],
                "estimated_cost_min": checked["estimated_cost_min"],
                "estimated_cost_max": checked["estimated_cost_max"],
                "currency": checked["currency"],
                "cost_estimate_basis": checked["cost_estimate_basis"],
                "cost_confirmed": True,
            },
        ),
    ):
        response = client.post(path, json=payload)
        assert response.status_code == 404
        serialized = str(response.json()).casefold()
        assert all(
            forbidden not in serialized
            for forbidden in ("sql", "traceback", "d:\\", "candidate", "999999")
        )
