from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.main import app
from app.models import CopyMatrix, ExecutionAttempt, ExecutionJob, MarketingStrategy
from app.providers import TextGenerationProvider
from app.schemas.copy import CopyJobEnqueueRequest
from app.services.copy_job_service import CopyJobService
from app.services.copy_preflight import CopyPreflightService


def queue_settings() -> Settings:
    return Settings(
        _env_file=None,
        qwen_api_key="fake-copy-queue-key",
        qwen_model="qwen-plus",
        token_plan_api_key_file="",
        enable_copy_execution=True,
    )


def copy_json() -> str:
    return json.dumps(
        {
            "copies": [
                {
                    "platform": platform,
                    "hook": f"{platform} hook",
                    "caption": f"{platform} caption",
                    "hashtags": [f"#{platform}"],
                    "cta": f"{platform} CTA",
                }
                for platform in ("TikTok", "Instagram", "Facebook", "Pinterest")
            ]
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
        return copy_json()


class FakeQwenFactory:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.state = {"constructed": 0, "calls": 0}
        self.error = error

    def __call__(self, settings: Settings) -> TextGenerationProvider:
        assert settings.qwen_model == "qwen-plus"
        self.state["constructed"] += 1
        return FakeQwenProvider(self.state, self.error)


def create_source(client: TestClient, db_session: Session) -> tuple[dict, dict, int]:
    product = client.post(
        "/api/v1/products",
        json={
            "name": "Portable Blender",
            "category": "Portable Kitchen Appliance",
            "description": "A portable blender for fresh drinks.",
            "selling_points": ["Portable", "USB rechargeable"],
            "target_markets": ["US"],
        },
    ).json()
    task = client.post(
        "/api/v1/marketing-tasks",
        json={
            "product_id": product["id"],
            "audience": "Target markets [US]. Busy professionals",
            "language": "English",
            "platforms": ["TikTok", "Instagram", "Facebook", "Pinterest"],
            "tone": "Clear and practical",
            "objective": "Build awareness",
        },
    ).json()
    strategy = MarketingStrategy(
        product_id=product["id"],
        positioning="Portable wellness",
        audience_insights=["Busy professionals"],
        angles=["Fresh drinks anywhere"],
        risks=["No unsupported claims"],
        evidence=["Portable and rechargeable"],
    )
    db_session.add(strategy)
    db_session.commit()
    return product, task, strategy.id


def preflight(client: TestClient, task_id: int, strategy_id: int) -> dict:
    response = client.get(
        f"/api/v1/marketing-tasks/{task_id}/strategies/{strategy_id}/copy-preflight"
    )
    assert response.status_code == 200
    assert response.json()["ready_for_execution"] is True
    return response.json()


def enqueue(
    client: TestClient,
    task_id: int,
    product_id: int,
    strategy_id: int,
    data: dict,
):
    return client.post(
        f"/api/v1/marketing-tasks/{task_id}/strategies/{strategy_id}/copy-jobs",
        json={
            "product_id": product_id,
            "strategy_id": strategy_id,
            "input_digest": data["input_digest"],
            "preflight_digest": data["preflight_digest"],
            "preflight_expires_at": data["expires_at"],
            "cost_confirmed": True,
        },
    )


def worker(
    db_session: Session, factory: FakeQwenFactory, worker_id: str
) -> ExecutionWorker:
    sessions = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    return ExecutionWorker(
        session_factory=sessions,
        registry=build_execution_handler_registry(
            session_factory=sessions,
            settings=queue_settings(),
            qwen_provider_factory=factory,
        ),
        worker_id=worker_id,
        lease_seconds=5,
        heartbeat_interval_seconds=0.05,
    )


def test_http_enqueue_and_fake_worker_end_to_end(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = queue_settings
    product, task, strategy_id = create_source(client, db_session)
    checked = preflight(client, task["id"], strategy_id)
    factory = FakeQwenFactory()

    first = enqueue(client, task["id"], product["id"], strategy_id, checked)
    second = enqueue(client, task["id"], product["id"], strategy_id, checked)
    assert first.status_code == second.status_code == 201
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert factory.state == {"constructed": 0, "calls": 0}
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 1
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0

    completed = worker(db_session, factory, "copy-e2e-worker").run_once()
    assert completed.status == WorkerRunStatus.SUCCEEDED
    assert factory.state == {"constructed": 1, "calls": 1}
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 1
    assert db_session.scalar(select(func.count(ExecutionAttempt.id))) == 1

    job = client.get(f"/api/v1/execution-jobs/{first.json()['job']['id']}").json()
    assert job["result_entity_type"] == "copy_matrix"
    exact = client.get(
        f"/api/v1/marketing-tasks/{task['id']}/strategies/{strategy_id}/copies/"
        f"{job['result_entity_id']}"
    )
    assert exact.status_code == 200
    assert [item["platform"] for item in exact.json()["copies"]] == [
        "TikTok",
        "Instagram",
        "Facebook",
        "Pinterest",
    ]

    listed = client.get(
        "/api/v1/execution-jobs",
        params={
            "job_type": "qwen.copy_matrix.generate.v1",
            "source_type": "marketing_strategy",
            "source_id": strategy_id,
        },
    )
    assert [item["id"] for item in listed.json()] == [job["id"]]
    restarted = worker(db_session, factory, "copy-worker-restarted").run_once()
    assert restarted.status == WorkerRunStatus.NO_JOB
    assert factory.state == {"constructed": 1, "calls": 1}
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 1


def test_enqueue_rejects_expired_changed_and_unconfirmed_inputs(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = queue_settings
    product, task, strategy_id = create_source(client, db_session)
    checked = preflight(client, task["id"], strategy_id)
    expired = dict(checked)
    expired["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert (
        enqueue(client, task["id"], product["id"], strategy_id, expired).status_code
        == 409
    )

    unconfirmed = client.post(
        f"/api/v1/marketing-tasks/{task['id']}/strategies/{strategy_id}/copy-jobs",
        json={
            "product_id": product["id"],
            "strategy_id": strategy_id,
            "input_digest": checked["input_digest"],
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
            "cost_confirmed": False,
        },
    )
    assert unconfirmed.status_code == 422

    db_session.get(MarketingStrategy, strategy_id).positioning = "Changed"
    db_session.commit()
    assert (
        enqueue(client, task["id"], product["id"], strategy_id, checked).status_code
        == 409
    )
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 0


def test_generic_queue_cannot_bypass_copy_confirmation(client: TestClient) -> None:
    response = client.post(
        "/api/v1/execution-jobs",
        json={
            "job_type": "qwen.copy_matrix.generate.v1",
            "source_type": "marketing_strategy",
            "source_id": 1,
            "input_digest": "a" * 64,
            "idempotency_key": "unsafe-generic-copy-job",
            "input_payload": {},
            "cost_confirmed": False,
        },
    )
    assert response.status_code == 409


def test_queued_job_survives_preflight_expiry(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = queue_settings
    product, task, strategy_id = create_source(client, db_session)
    enqueued_at = datetime.now(UTC) - timedelta(hours=1)
    expires_at = enqueued_at + timedelta(seconds=30)
    checked = CopyPreflightService(
        db_session, queue_settings(), now=lambda: enqueued_at
    ).run(task["id"], strategy_id, expires_at=expires_at)
    created = CopyJobService(
        db_session, queue_settings(), now=lambda: enqueued_at
    ).enqueue(
        task["id"],
        strategy_id,
        CopyJobEnqueueRequest(
            product_id=product["id"],
            strategy_id=strategy_id,
            input_digest=checked.input_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            cost_confirmed=True,
        ),
    )
    factory = FakeQwenFactory()
    result = worker(db_session, factory, "copy-expired-worker").run_once()
    assert created.job.status == "QUEUED"
    assert result.status == WorkerRunStatus.SUCCEEDED
    assert factory.state == {"constructed": 1, "calls": 1}


def test_provider_exception_remains_submit_unknown(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = queue_settings
    product, task, strategy_id = create_source(client, db_session)
    created = enqueue(
        client,
        task["id"],
        product["id"],
        strategy_id,
        preflight(client, task["id"], strategy_id),
    ).json()
    factory = FakeQwenFactory(error=RuntimeError("fake uncertain response"))
    result = worker(db_session, factory, "copy-unknown-worker").run_once()
    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    retry = client.post(
        f"/api/v1/execution-jobs/{created['job']['id']}/retry",
        json={"retry_confirmed": True},
    )
    assert retry.status_code == 409
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0
