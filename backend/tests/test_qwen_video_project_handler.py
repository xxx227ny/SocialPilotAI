from __future__ import annotations

import json
import threading
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.base import Base
from app.execution.handlers.qwen_video_project import (
    QWEN_VIDEO_PROJECT_GENERATE_V1,
    QwenVideoProjectGenerateV1Handler,
    QwenVideoProjectGenerateV1Input,
)
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import (
    CopyMatrix,
    ExecutionJob,
    MarketingStrategy,
    Product,
    VideoProject,
)
from app.providers import TextGenerationProvider
from app.repositories.video import VideoProjectRepository
from app.schemas.execution import ExecutionJobCreate, ExecutionJobRetryRequest
from app.schemas.video import InitialVideoProjectSourceRequest
from app.services.execution_queue_service import ExecutionQueueService
from app.services.initial_video_project_preflight import (
    InitialVideoProjectPreflightService,
)
from tests.test_content_studio_service import add_video_sources, valid_plan


class FakeQwenProvider(TextGenerationProvider):
    def __init__(
        self,
        *,
        result: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or valid_plan()
        self.error = error
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, prompt: str) -> str:
        assert "structured short-video production plan" in prompt
        with self._lock:
            self.calls += 1
        if self.error is not None:
            raise self.error
        return json.dumps(self.result)


@pytest.fixture
def video_sessions(
    tmp_path: Path,
) -> Generator[sessionmaker[Session], None, None]:
    database = tmp_path / "qwen-video-project-handler.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    yield sessions
    engine.dispose()


def settings() -> Settings:
    return Settings(
        _env_file=None,
        qwen_api_key="fake-video-handler-key",
        enable_video_project_execution=True,
    )


def create_job(
    sessions: sessionmaker[Session],
    *,
    suffix: str,
) -> tuple[int, int, int, int]:
    with sessions() as session:
        product, strategy, copy_matrix = add_video_sources(session)
        source = InitialVideoProjectSourceRequest(
            strategy_id=strategy.id,
            copy_matrix_id=copy_matrix.id,
            platform="TikTok",
            duration_seconds=30,
            aspect_ratio="9:16",
        )
        checked = InitialVideoProjectPreflightService(
            session, settings()
        ).run(product.id, source)
        payload = QwenVideoProjectGenerateV1Input(
            product_id=product.id,
            marketing_strategy_id=strategy.id,
            copy_matrix_id=copy_matrix.id,
            platform=source.platform,
            duration_seconds=source.duration_seconds,
            aspect_ratio=source.aspect_ratio,
            frozen_input_digest=checked.input_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
        )
        created = ExecutionQueueService(session).create(
            ExecutionJobCreate(
                job_type=QWEN_VIDEO_PROJECT_GENERATE_V1,
                source_type="product",
                source_id=product.id,
                input_digest=checked.input_digest,
                idempotency_key=f"qwen-video-handler-{suffix}",
                input_payload=payload.model_dump(mode="json"),
                concurrency_key=f"qwen-video-project-product-{product.id}",
                cost_confirmed=True,
                max_attempts=2,
            )
        )
        return created.job.id, product.id, strategy.id, copy_matrix.id


def make_worker(
    sessions: sessionmaker[Session],
    provider: TextGenerationProvider,
    worker_id: str,
) -> ExecutionWorker:
    registry = ExecutionHandlerRegistry()
    registry.register(
        QwenVideoProjectGenerateV1Handler(
            session_factory=sessions,
            provider=provider,
            settings=settings(),
        )
    )
    return ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id=worker_id,
        lease_seconds=5,
        heartbeat_interval_seconds=0.05,
    )


def test_fake_qwen_success_persists_exact_video_project_result(
    video_sessions: sessionmaker[Session],
) -> None:
    job_id, product_id, strategy_id, copy_matrix_id = create_job(
        video_sessions, suffix="success"
    )
    provider = FakeQwenProvider()

    result = make_worker(
        video_sessions, provider, "video-worker-success"
    ).run_once()

    assert result.status == WorkerRunStatus.SUCCEEDED
    assert provider.calls == 1
    with video_sessions() as session:
        assert session.scalar(select(func.count(VideoProject.id))) == 1
        job = ExecutionQueueService(session).get(job_id)
        assert job.provider_name == "qwen"
        assert job.result_entity_type == "video_project"
        assert job.result_entity_id is not None
        project = session.get(VideoProject, job.result_entity_id)
        assert project is not None
        assert (project.product_id, project.marketing_strategy_id) == (
            product_id,
            strategy_id,
        )
        assert project.copy_matrix_id == copy_matrix_id
        assert job.attempts[0].provider_call_count == 1
        assert job.attempts[0].external_submission_possible is True


def test_two_workers_generate_only_one_video_project(
    video_sessions: sessionmaker[Session],
) -> None:
    create_job(video_sessions, suffix="concurrent")
    provider = FakeQwenProvider()
    barrier = threading.Barrier(3)
    results = []

    def run(worker_id: str) -> None:
        worker = make_worker(video_sessions, provider, worker_id)
        barrier.wait()
        results.append(worker.run_once())

    threads = [
        threading.Thread(target=run, args=(f"video-worker-{index}",))
        for index in (1, 2)
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(result.status for result in results) == [
        WorkerRunStatus.NO_JOB,
        WorkerRunStatus.SUCCEEDED,
    ]
    assert provider.calls == 1
    with video_sessions() as session:
        assert session.scalar(select(func.count(VideoProject.id))) == 1


@pytest.mark.parametrize("change", ["product", "strategy", "copy", "relation"])
def test_changed_frozen_source_fails_before_provider(
    video_sessions: sessionmaker[Session], change: str
) -> None:
    job_id, product_id, strategy_id, copy_matrix_id = create_job(
        video_sessions, suffix=f"changed-{change}"
    )
    with video_sessions() as session:
        if change == "product":
            session.get(Product, product_id).description = "Changed description"
        elif change == "strategy":
            session.get(MarketingStrategy, strategy_id).positioning = "Changed"
        elif change == "copy":
            matrix = session.get(CopyMatrix, copy_matrix_id)
            matrix.copies = [
                ({**item, "hook": "Changed"} if index == 0 else item)
                for index, item in enumerate(matrix.copies)
            ]
        else:
            other = Product(
                name="Other",
                category="Other",
                description="Other description",
                selling_points=["Other"],
                target_markets=["US"],
            )
            session.add(other)
            session.flush()
            session.get(MarketingStrategy, strategy_id).product_id = other.id
        session.commit()
    provider = FakeQwenProvider()

    result = make_worker(
        video_sessions, provider, f"video-worker-changed-{change}"
    ).run_once()

    assert result.status == WorkerRunStatus.FAILED
    assert provider.calls == 0
    with video_sessions() as session:
        job = ExecutionQueueService(session).get(job_id)
        assert job.uncertain is False
        retried = ExecutionQueueService(session).retry(
            job_id, ExecutionJobRetryRequest(retry_confirmed=True)
        )
        assert retried.status == "QUEUED"


@pytest.mark.parametrize("failure", ["provider", "schema", "save"])
def test_post_submission_failure_is_unknown_and_not_retryable(
    video_sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    job_id, _, _, _ = create_job(video_sessions, suffix=f"unknown-{failure}")
    invalid = valid_plan()
    if failure == "schema":
        invalid["scenes"] = []
    provider = FakeQwenProvider(
        result=invalid,
        error=(
            RuntimeError("fake uncertain transport")
            if failure == "provider"
            else None
        ),
    )
    if failure == "save":
        monkeypatch.setattr(
            VideoProjectRepository,
            "create_for_exact_chain",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("fake save failure")
            ),
        )

    result = make_worker(
        video_sessions, provider, f"video-worker-unknown-{failure}"
    ).run_once()

    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert provider.calls == 1
    with video_sessions() as session:
        assert session.scalar(select(func.count(VideoProject.id))) == 0
        job = ExecutionQueueService(session).get(job_id)
        assert job.uncertain is True
        with pytest.raises(AppError, match="Only certain failed jobs"):
            ExecutionQueueService(session).retry(
                job_id, ExecutionJobRetryRequest(retry_confirmed=True)
            )


def test_payload_and_error_fields_are_secret_free(
    video_sessions: sessionmaker[Session],
) -> None:
    job_id, _, _, _ = create_job(video_sessions, suffix="secret-safe")
    with video_sessions() as session:
        job = session.get(ExecutionJob, job_id)
        serialized = json.dumps(
            {
                "payload": job.input_payload,
                "safe_error_code": job.safe_error_code,
                "safe_error_details": job.safe_error_details,
            }
        ).casefold()
    for forbidden in (
        "fake-video-handler-key",
        "api_key",
        "authorization",
        "cookie",
        "token",
        "secret",
    ):
        assert forbidden not in serialized
