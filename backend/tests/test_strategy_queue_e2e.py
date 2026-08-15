from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.execution.handlers.video_composition import (
    VideoCompositionRenderV1Handler,
    VideoCompositionRenderV1Input,
)
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.main import app
from app.models import ExecutionJob, MarketingStrategy, Product
from app.providers import TextGenerationProvider
from app.schemas.strategy import StrategyJobEnqueueRequest
from app.services.strategy_job_service import StrategyJobService
from app.services.strategy_preflight import StrategyPreflightService


def queue_settings() -> Settings:
    return Settings(
        _env_file=None,
        qwen_api_key="fake-strategy-queue-key",
        enable_strategy_execution=True,
    )


def strategy_json() -> str:
    return json.dumps(
        {
            "positioning": "Portable wellness for busy routines.",
            "audience_insights": ["Busy professionals value convenience."],
            "angles": ["Fresh drinks anywhere"],
            "risks": ["Avoid unsupported health claims."],
            "evidence": ["Portable and USB rechargeable."],
        }
    )


class FakeQwenProvider(TextGenerationProvider):
    def __init__(self, state: dict[str, int], error: Exception | None = None):
        self.state = state
        self.error = error

    def generate(self, prompt: str) -> str:
        assert "Portable Blender" in prompt
        self.state["calls"] += 1
        if self.error is not None:
            raise self.error
        return strategy_json()


class FakeQwenFactory:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.state = {"constructed": 0, "calls": 0}
        self.error = error

    def __call__(self, settings: Settings) -> TextGenerationProvider:
        assert settings.qwen_model == "qwen-plus"
        self.state["constructed"] += 1
        return FakeQwenProvider(self.state, self.error)


def create_source(client: TestClient) -> tuple[dict, dict]:
    product_response = client.post(
        "/api/v1/products",
        json={
            "name": "Portable Blender",
            "category": "Portable Kitchen Appliance",
            "description": "A portable blender for fresh drinks.",
            "selling_points": ["Portable", "USB rechargeable"],
            "target_markets": ["US"],
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()
    brief_response = client.post(
        "/api/v1/marketing-tasks",
        json={
            "product_id": product["id"],
            "audience": "Target markets [US]. Busy professionals",
            "language": "English",
            "platforms": ["TikTok", "Instagram"],
            "tone": "Clear and practical",
            "objective": "Build awareness",
        },
    )
    assert brief_response.status_code == 201
    return product, brief_response.json()


def preflight(client: TestClient, task_id: int) -> dict:
    response = client.get(f"/api/v1/marketing-tasks/{task_id}/strategy-preflight")
    assert response.status_code == 200
    assert response.json()["ready_for_execution"] is True
    return response.json()


def enqueue(client: TestClient, task_id: int, product_id: int, data: dict):
    return client.post(
        f"/api/v1/marketing-tasks/{task_id}/strategy-jobs",
        json={
            "product_id": product_id,
            "input_digest": data["input_digest"],
            "preflight_digest": data["preflight_digest"],
            "preflight_expires_at": data["expires_at"],
            "cost_confirmed": True,
        },
    )


def worker(
    db_session: Session,
    factory: FakeQwenFactory,
    worker_id: str,
) -> ExecutionWorker:
    sessions = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=queue_settings(),
        qwen_provider_factory=factory,
    )
    return ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id=worker_id,
        lease_seconds=5,
        heartbeat_interval_seconds=0.05,
    )


def test_http_enqueue_is_provider_free_and_worker_restores_exact_result(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = queue_settings
    product, task = create_source(client)
    checked = preflight(client, task["id"])
    factory = FakeQwenFactory()
    registry = build_execution_handler_registry(
        session_factory=sessionmaker(bind=db_session.get_bind()),
        settings=queue_settings(),
        qwen_provider_factory=factory,
    )
    assert registry.job_types == (
        "instagram.publish.finalize.v1",
        "instagram.publish.refresh.v1",
        "instagram.publish.submit.v1",
        "qwen.copy_matrix.generate.v1",
        "qwen.strategy.generate.v1",
        "qwen.video_project.generate.v1",
        "tiktok.publish.creator_info.v1",
        "tiktok.publish.refresh.v1",
        "tiktok.publish.submit.v1",
        "video.batch.variant.prepare.v1",
        "video.composition.enhance.v1",
        "video.composition.render.v1",
        "wanx.video_render.refresh.v1",
        "wanx.video_render.submit.v1",
        "youtube.publish.refresh.v1",
        "youtube.publish.submit.v1",
    )
    composition_handler = registry.resolve("video.composition.render.v1")
    assert isinstance(composition_handler, VideoCompositionRenderV1Handler)
    assert composition_handler.input_schema is VideoCompositionRenderV1Input
    assert registry.job_types.count("video.composition.render.v1") == 1
    assert registry.job_types.count("video.composition.enhance.v1") == 1
    assert factory.state == {"constructed": 0, "calls": 0}

    first = enqueue(client, task["id"], product["id"], checked)
    second = enqueue(client, task["id"], product["id"], checked)
    assert first.status_code == second.status_code == 201
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert factory.state == {"constructed": 0, "calls": 0}
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 1
    assert db_session.scalar(select(func.count(MarketingStrategy.id))) == 0

    completed = worker(db_session, factory, "strategy-e2e-worker").run_once()
    assert completed.status == WorkerRunStatus.SUCCEEDED
    assert factory.state == {"constructed": 1, "calls": 1}
    assert db_session.scalar(select(func.count(MarketingStrategy.id))) == 1

    job_id = first.json()["job"]["id"]
    job = client.get(f"/api/v1/execution-jobs/{job_id}").json()
    assert job["status"] == "SUCCEEDED"
    assert job["result_entity_type"] == "marketing_strategy"
    assert job["result_entity_id"] is not None
    exact = client.get(
        f"/api/v1/marketing-tasks/{task['id']}/strategies/{job['result_entity_id']}"
    )
    assert exact.status_code == 200
    assert exact.json()["id"] == job["result_entity_id"]

    restarted = worker(db_session, factory, "strategy-e2e-worker-restarted").run_once()
    assert restarted.status == WorkerRunStatus.NO_JOB
    assert factory.state == {"constructed": 1, "calls": 1}
    assert db_session.scalar(select(func.count(MarketingStrategy.id))) == 1


def test_expired_or_changed_preflight_is_rejected_before_queue(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = queue_settings
    product, task = create_source(client)
    checked = preflight(client, task["id"])
    expired = dict(checked)
    expired["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    expired_response = enqueue(client, task["id"], product["id"], expired)
    assert expired_response.status_code == 409

    db_session.get(Product, product["id"]).description = "Changed input"
    db_session.commit()
    changed_response = enqueue(client, task["id"], product["id"], checked)
    assert changed_response.status_code == 409
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 0
    assert db_session.scalar(select(func.count(MarketingStrategy.id))) == 0


def test_generic_queue_cannot_bypass_strategy_confirmation(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/execution-jobs",
        json={
            "job_type": "qwen.strategy.generate.v1",
            "source_type": "marketing_brief",
            "source_id": 1,
            "input_digest": "a" * 64,
            "idempotency_key": "unsafe-generic-strategy-job",
            "input_payload": {},
            "cost_confirmed": False,
        },
    )
    assert response.status_code == 409


def test_generic_queue_cannot_create_video_composition_job(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/execution-jobs",
        json={
            "job_type": "video.composition.render.v1",
            "source_type": "video_composition",
            "source_id": 1,
            "input_digest": "a" * 64,
            "idempotency_key": "unsafe-generic-composition-job",
            "input_payload": {},
            "cost_confirmed": True,
        },
    )
    assert response.status_code == 409


def test_source_change_after_enqueue_fails_before_provider_and_can_retry(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = queue_settings
    product, task = create_source(client)
    created = enqueue(
        client, task["id"], product["id"], preflight(client, task["id"])
    ).json()
    db_session.get(Product, product["id"]).description = "Changed after queue"
    db_session.commit()
    factory = FakeQwenFactory()

    failed = worker(db_session, factory, "strategy-change-worker").run_once()
    assert failed.status == WorkerRunStatus.FAILED
    assert factory.state == {"constructed": 0, "calls": 0}
    retry = client.post(
        f"/api/v1/execution-jobs/{created['job']['id']}/retry",
        json={"retry_confirmed": True},
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "QUEUED"


def test_queued_job_remains_valid_after_preflight_expiry(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = queue_settings
    product, task = create_source(client)
    enqueued_at = datetime.now(UTC) - timedelta(hours=1)
    expires_at = enqueued_at + timedelta(seconds=30)
    checked = StrategyPreflightService(
        db_session, queue_settings(), now=lambda: enqueued_at
    ).run(task["id"], expires_at=expires_at)
    created = StrategyJobService(
        db_session, queue_settings(), now=lambda: enqueued_at
    ).enqueue(
        task["id"],
        StrategyJobEnqueueRequest(
            product_id=product["id"],
            input_digest=checked.input_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            cost_confirmed=True,
        ),
    )
    factory = FakeQwenFactory()

    result = worker(db_session, factory, "strategy-expired-worker").run_once()

    assert created.job.status == "QUEUED"
    assert result.status == WorkerRunStatus.SUCCEEDED
    assert factory.state == {"constructed": 1, "calls": 1}


def test_provider_exception_remains_submit_unknown_without_retry(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = queue_settings
    product, task = create_source(client)
    created = enqueue(
        client, task["id"], product["id"], preflight(client, task["id"])
    ).json()
    factory = FakeQwenFactory(error=RuntimeError("fake uncertain response"))

    unknown = worker(db_session, factory, "strategy-unknown-worker").run_once()
    assert unknown.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert factory.state == {"constructed": 1, "calls": 1}
    retry = client.post(
        f"/api/v1/execution-jobs/{created['job']['id']}/retry",
        json={"retry_confirmed": True},
    )
    assert retry.status_code == 409
    assert db_session.scalar(select(func.count(MarketingStrategy.id))) == 0


def test_exact_strategy_read_rejects_cross_product_identity(
    client: TestClient, db_session: Session
) -> None:
    first_product, task = create_source(client)
    other = Product(
        name="Other Product",
        category="Other",
        description="Other description",
        selling_points=["Other point"],
        target_markets=["US"],
    )
    db_session.add(other)
    db_session.flush()
    strategy = MarketingStrategy(
        product_id=other.id,
        positioning="Other",
        audience_insights=["Other"],
        angles=["Other"],
        risks=["Other"],
        evidence=["Other"],
    )
    db_session.add(strategy)
    db_session.commit()

    response = client.get(
        f"/api/v1/marketing-tasks/{task['id']}/strategies/{strategy.id}"
    )
    assert first_product["id"] != other.id
    assert response.status_code == 409
