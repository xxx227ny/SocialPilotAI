from __future__ import annotations

import hashlib
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
from app.execution.handlers.qwen_strategy import (
    QWEN_STRATEGY_GENERATE_V1,
    QwenStrategyGenerateV1Handler,
    QwenStrategyGenerateV1Input,
)
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import ExecutionJob, MarketingBrief, MarketingStrategy, Product
from app.providers import TextGenerationProvider
from app.providers.live_configuration import (
    provider_error_from_metadata,
    provider_failure_metadata,
)
from app.schemas.execution import ExecutionJobCreate, ExecutionJobRetryRequest
from app.services.execution_queue_service import ExecutionQueueService
from app.services.strategy_preflight import StrategyPreflightService


def strategy_json() -> str:
    return json.dumps(
        {
            "positioning": "Portable wellness for busy routines.",
            "audience_insights": ["Busy professionals value convenience."],
            "angles": ["Fresh drinks anywhere"],
            "risks": ["Avoid unsupported health claims."],
            "evidence": ["The product is portable and USB rechargeable."],
        }
    )


class FakeQwenProvider(TextGenerationProvider):
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, prompt: str) -> str:
        assert "Portable Blender" in prompt
        with self._lock:
            self.calls += 1
        if self.error is not None:
            raise self.error
        return strategy_json()


@pytest.fixture
def strategy_sessions(
    tmp_path: Path,
) -> Generator[sessionmaker[Session], None, None]:
    database = tmp_path / "qwen-strategy-handler.db"
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
        qwen_api_key="fake-qwen-handler-key",
        enable_strategy_execution=True,
    )


def create_sources(
    sessions: sessionmaker[Session],
) -> tuple[int, int, str]:
    with sessions() as session:
        product = Product(
            name="Portable Blender",
            category="Portable Kitchen Appliance",
            description="A portable blender for fresh drinks.",
            selling_points=["Portable design", "USB rechargeable"],
            target_markets=["US"],
        )
        session.add(product)
        session.flush()
        brief = MarketingBrief(
            product_id=product.id,
            audience="Target markets [US]. Busy professionals",
            language="English",
            platforms=["TikTok", "Instagram"],
            tone="Clear and practical",
            objective="Build awareness",
        )
        session.add(brief)
        session.commit()
        preflight = StrategyPreflightService(session, settings()).run(brief.id)
        return product.id, brief.id, preflight.input_digest


def create_job(
    sessions: sessionmaker[Session],
    *,
    product_id: int,
    brief_id: int,
    digest: str,
    suffix: str,
    preflight_product_id: int | None = None,
    preflight_brief_id: int | None = None,
) -> int:
    payload = QwenStrategyGenerateV1Input(
        product_id=product_id,
        marketing_brief_id=brief_id,
        preflight_product_id=preflight_product_id or product_id,
        preflight_marketing_brief_id=preflight_brief_id or brief_id,
        frozen_digest=digest,
    )
    with sessions() as session:
        created = ExecutionQueueService(session).create(
            ExecutionJobCreate(
                job_type=QWEN_STRATEGY_GENERATE_V1,
                source_type="marketing_brief",
                source_id=brief_id,
                input_digest=hashlib.sha256(
                    json.dumps(payload.model_dump(), sort_keys=True).encode()
                ).hexdigest(),
                idempotency_key=f"qwen-strategy-handler-{suffix}",
                input_payload=payload.model_dump(),
                concurrency_key=f"qwen-strategy-product-{product_id}",
                max_attempts=2,
            )
        )
        return created.job.id


def make_worker(
    sessions: sessionmaker[Session],
    provider: TextGenerationProvider,
    worker_id: str,
) -> ExecutionWorker:
    registry = ExecutionHandlerRegistry()
    registry.register(
        QwenStrategyGenerateV1Handler(
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


def read_job(sessions: sessionmaker[Session], job_id: int) -> ExecutionJob:
    with sessions() as session:
        job = ExecutionQueueService(session).get(job_id)
        session.expunge_all()
        return job


def test_fake_qwen_success_persists_exact_strategy_result(
    strategy_sessions: sessionmaker[Session],
) -> None:
    product_id, brief_id, digest = create_sources(strategy_sessions)
    provider = FakeQwenProvider()
    job_id = create_job(
        strategy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        digest=digest,
        suffix="success",
    )

    result = make_worker(
        strategy_sessions, provider, "strategy-worker-success"
    ).run_once()

    assert result.status == WorkerRunStatus.SUCCEEDED
    assert provider.calls == 1
    with strategy_sessions() as session:
        assert session.scalar(select(func.count(MarketingStrategy.id))) == 1
        job = ExecutionQueueService(session).get(job_id)
        assert job.result_entity_type == "marketing_strategy"
        assert job.result_entity_id is not None
        assert session.get(MarketingStrategy, job.result_entity_id) is not None
        assert job.provider_operation_id is None
        assert job.attempts[0].provider_call_count == 1
        assert job.attempts[0].external_submission_possible is True


def test_two_workers_generate_only_one_strategy(
    strategy_sessions: sessionmaker[Session],
) -> None:
    product_id, brief_id, digest = create_sources(strategy_sessions)
    provider = FakeQwenProvider()
    job_id = create_job(
        strategy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        digest=digest,
        suffix="concurrent",
    )
    barrier = threading.Barrier(3)
    results = []

    def run(worker_id: str) -> None:
        worker = make_worker(strategy_sessions, provider, worker_id)
        barrier.wait()
        results.append(worker.run_once())

    threads = [
        threading.Thread(target=run, args=(f"strategy-worker-{index}",))
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
    with strategy_sessions() as session:
        assert session.scalar(select(func.count(MarketingStrategy.id))) == 1
        assert ExecutionQueueService(session).get(job_id).attempt_count == 1


@pytest.mark.parametrize("change", ["relationship", "digest"])
def test_changed_source_identity_or_digest_fails_before_provider(
    strategy_sessions: sessionmaker[Session], change: str
) -> None:
    product_id, brief_id, digest = create_sources(strategy_sessions)
    job_id = create_job(
        strategy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        digest=digest,
        suffix=f"changed-{change}",
    )
    with strategy_sessions() as session:
        if change == "relationship":
            other = Product(
                name="Other Product",
                category="Other",
                description="Other description",
                selling_points=["Other point"],
                target_markets=["US"],
            )
            session.add(other)
            session.flush()
            session.get(MarketingBrief, brief_id).product_id = other.id
        else:
            session.get(Product, product_id).description = "Changed description"
        session.commit()
    provider = FakeQwenProvider()

    result = make_worker(
        strategy_sessions, provider, f"strategy-worker-{change}"
    ).run_once()

    assert result.status == WorkerRunStatus.FAILED
    job = read_job(strategy_sessions, job_id)
    assert job.uncertain is False
    assert job.result_entity_id is None
    assert provider.calls == 0
    with strategy_sessions() as session:
        retried = ExecutionQueueService(session).retry(
            job_id, ExecutionJobRetryRequest(retry_confirmed=True)
        )
        assert retried.status == "QUEUED"


def test_classified_quota_failure_is_certain_and_retryable(
    strategy_sessions: sessionmaker[Session],
) -> None:
    product_id, brief_id, digest = create_sources(strategy_sessions)
    error = provider_error_from_metadata(
        provider_failure_metadata(
            provider="qwen",
            phase="response",
            http_status=429,
            uncertain=False,
            potentially_billable=False,
        )
    )
    provider = FakeQwenProvider(error=error)
    job_id = create_job(
        strategy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        digest=digest,
        suffix="quota",
    )

    result = make_worker(
        strategy_sessions, provider, "strategy-worker-quota"
    ).run_once()

    assert result.status == WorkerRunStatus.FAILED
    assert provider.calls == 1
    job = read_job(strategy_sessions, job_id)
    assert job.uncertain is False
    assert job.safe_error_code == "STRATEGY_RATE_OR_QUOTA_LIMITED"
    assert job.safe_error_details["http_status"] == 429
    with strategy_sessions() as session:
        retried = ExecutionQueueService(session).retry(
            job_id, ExecutionJobRetryRequest(retry_confirmed=True)
        )
        assert retried.status == "QUEUED"


def test_provider_exception_is_submit_unknown_and_never_retryable(
    strategy_sessions: sessionmaker[Session],
) -> None:
    product_id, brief_id, digest = create_sources(strategy_sessions)
    provider = FakeQwenProvider(error=RuntimeError("uncertain fake transport"))
    job_id = create_job(
        strategy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        digest=digest,
        suffix="uncertain",
    )

    result = make_worker(
        strategy_sessions, provider, "strategy-worker-uncertain"
    ).run_once()

    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert provider.calls == 1
    job = read_job(strategy_sessions, job_id)
    assert job.uncertain is True
    assert job.result_entity_id is None
    with (
        strategy_sessions() as session,
        pytest.raises(AppError, match="Only certain failed jobs"),
    ):
        ExecutionQueueService(session).retry(
            job_id, ExecutionJobRetryRequest(retry_confirmed=True)
        )


def test_payload_error_and_api_shape_are_secret_free(
    strategy_sessions: sessionmaker[Session],
) -> None:
    product_id, brief_id, digest = create_sources(strategy_sessions)
    provider = FakeQwenProvider()
    job_id = create_job(
        strategy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        digest=digest,
        suffix="secret-safe",
        preflight_product_id=product_id + 1,
    )

    make_worker(strategy_sessions, provider, "strategy-worker-secret-safe").run_once()
    job = read_job(strategy_sessions, job_id)
    serialized = json.dumps(
        {
            "payload": job.input_payload,
            "safe_error_code": job.safe_error_code,
            "safe_error_details": job.safe_error_details,
            "result_entity_type": job.result_entity_type,
            "result_entity_id": job.result_entity_id,
        }
    ).casefold()

    assert provider.calls == 0
    for forbidden in (
        "fake-qwen-handler-key",
        "api_key",
        "authorization",
        "cookie",
        "token",
        "secret",
    ):
        assert forbidden not in serialized
