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
from app.models import ExecutionAttempt, ExecutionJob, VideoProject
from app.providers import TextGenerationProvider
from app.schemas.video import (
    InitialVideoProjectExecutionRequest,
    InitialVideoProjectSourceRequest,
)
from app.services.initial_video_project_job_service import (
    InitialVideoProjectJobService,
)
from app.services.initial_video_project_preflight import (
    InitialVideoProjectPreflightService,
)
from tests.test_content_studio_service import add_video_sources, valid_plan


def queue_settings() -> Settings:
    return Settings(
        _env_file=None,
        qwen_api_key="fake-video-queue-key",
        enable_video_project_execution=True,
    )


class FakeQwenProvider(TextGenerationProvider):
    def __init__(self, state: dict[str, int], error: Exception | None = None):
        self.state = state
        self.error = error

    def generate(self, prompt: str) -> str:
        assert "structured short-video production plan" in prompt
        self.state["calls"] += 1
        if self.error is not None:
            raise self.error
        return json.dumps(valid_plan())


class FakeQwenFactory:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.state = {"constructed": 0, "calls": 0}
        self.error = error

    def __call__(self, settings: Settings) -> TextGenerationProvider:
        assert settings.qwen_model == "qwen-plus"
        self.state["constructed"] += 1
        return FakeQwenProvider(self.state, self.error)


def source_payload(strategy_id: int, copy_matrix_id: int) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "copy_matrix_id": copy_matrix_id,
        "platform": "TikTok",
        "duration_seconds": 30,
        "aspect_ratio": "9:16",
    }


def preflight(
    client: TestClient,
    product_id: int,
    strategy_id: int,
    copy_matrix_id: int,
) -> dict:
    response = client.post(
        f"/api/v1/products/{product_id}/video-projects/preflight",
        json=source_payload(strategy_id, copy_matrix_id),
    )
    assert response.status_code == 200
    assert response.json()["ready_for_execution"] is True
    return response.json()


def enqueue(
    client: TestClient,
    product_id: int,
    strategy_id: int,
    copy_matrix_id: int,
    checked: dict,
):
    return client.post(
        f"/api/v1/products/{product_id}/video-projects/execute",
        json={
            **source_payload(strategy_id, copy_matrix_id),
            "product_id": product_id,
            "input_digest": checked["input_digest"],
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
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
    product, strategy, copy_matrix = add_video_sources(db_session)
    checked = preflight(client, product.id, strategy.id, copy_matrix.id)
    factory = FakeQwenFactory()

    first = enqueue(client, product.id, strategy.id, copy_matrix.id, checked)
    second = enqueue(client, product.id, strategy.id, copy_matrix.id, checked)
    assert first.status_code == second.status_code == 201
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert factory.state == {"constructed": 0, "calls": 0}
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 1
    assert db_session.scalar(select(func.count(VideoProject.id))) == 0

    completed = worker(db_session, factory, "video-e2e-worker").run_once()
    assert completed.status == WorkerRunStatus.SUCCEEDED
    assert factory.state == {"constructed": 1, "calls": 1}
    assert db_session.scalar(select(func.count(VideoProject.id))) == 1
    assert db_session.scalar(select(func.count(ExecutionAttempt.id))) == 1

    job = client.get(
        f"/api/v1/execution-jobs/{first.json()['job']['id']}"
    ).json()
    assert job["result_entity_type"] == "video_project"
    exact = client.get(f"/api/v1/video-projects/{job['result_entity_id']}")
    assert exact.status_code == 200
    assert exact.json()["id"] == job["result_entity_id"]
    assert exact.json()["product_id"] == product.id
    assert exact.json()["marketing_strategy_id"] == strategy.id
    assert exact.json()["copy_matrix_id"] == copy_matrix.id

    listed = client.get(
        "/api/v1/execution-jobs",
        params={
            "job_type": "qwen.video_project.generate.v1",
            "source_type": "product",
            "source_id": product.id,
        },
    )
    assert [item["id"] for item in listed.json()] == [job["id"]]
    restarted = worker(
        db_session, factory, "video-worker-restarted"
    ).run_once()
    assert restarted.status == WorkerRunStatus.NO_JOB
    assert factory.state == {"constructed": 1, "calls": 1}
    assert db_session.scalar(select(func.count(VideoProject.id))) == 1


def test_generic_queue_cannot_bypass_video_confirmation(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/api/v1/execution-jobs",
        json={
            "job_type": "qwen.video_project.generate.v1",
            "source_type": "product",
            "source_id": 1,
            "input_digest": "a" * 64,
            "idempotency_key": "unsafe-generic-video-project-job",
            "input_payload": {"private": "must-not-be-reflected"},
            "cost_confirmed": False,
        },
    )
    assert response.status_code == 409
    serialized = response.text.casefold()
    assert "must-not-be-reflected" not in serialized
    assert "a" * 64 not in serialized
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 0
    assert db_session.scalar(select(func.count(VideoProject.id))) == 0


def test_queued_job_survives_preflight_expiry(
    db_session: Session,
) -> None:
    product, strategy, copy_matrix = add_video_sources(db_session)
    enqueued_at = datetime.now(UTC) - timedelta(hours=1)
    expires_at = enqueued_at + timedelta(seconds=30)
    source = InitialVideoProjectSourceRequest(
        **source_payload(strategy.id, copy_matrix.id)
    )
    checked = InitialVideoProjectPreflightService(
        db_session, queue_settings(), now=lambda: enqueued_at
    ).run(product.id, source, expires_at=expires_at)
    created = InitialVideoProjectJobService(
        db_session, queue_settings(), now=lambda: enqueued_at
    ).enqueue(
        product.id,
        InitialVideoProjectExecutionRequest(
            **source.model_dump(),
            product_id=product.id,
            input_digest=checked.input_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            cost_confirmed=True,
        ),
    )
    factory = FakeQwenFactory()
    result = worker(db_session, factory, "video-expired-worker").run_once()
    assert created.job.status == "QUEUED"
    assert result.status == WorkerRunStatus.SUCCEEDED
    assert factory.state == {"constructed": 1, "calls": 1}


def test_provider_exception_remains_submit_unknown(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = queue_settings
    product, strategy, copy_matrix = add_video_sources(db_session)
    created = enqueue(
        client,
        product.id,
        strategy.id,
        copy_matrix.id,
        preflight(client, product.id, strategy.id, copy_matrix.id),
    ).json()
    factory = FakeQwenFactory(error=RuntimeError("fake uncertain response"))
    result = worker(db_session, factory, "video-unknown-worker").run_once()
    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    retry = client.post(
        f"/api/v1/execution-jobs/{created['job']['id']}/retry",
        json={"retry_confirmed": True},
    )
    assert retry.status_code == 409
    assert factory.state == {"constructed": 1, "calls": 1}
    assert db_session.scalar(select(func.count(VideoProject.id))) == 0
