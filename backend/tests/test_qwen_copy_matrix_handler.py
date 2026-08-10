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
from app.execution.handlers.qwen_copy_matrix import (
    QWEN_COPY_MATRIX_GENERATE_V1,
    QwenCopyMatrixGenerateV1Handler,
    QwenCopyMatrixGenerateV1Input,
)
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import (
    CopyMatrix,
    ExecutionJob,
    MarketingBrief,
    MarketingStrategy,
    Product,
)
from app.providers import TextGenerationProvider
from app.schemas.execution import ExecutionJobCreate, ExecutionJobRetryRequest
from app.services.copy_preflight import CopyPreflightService
from app.services.execution_queue_service import ExecutionQueueService


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
                for platform in ("TikTok", "Instagram", "Facebook")
            ]
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
        return copy_json()


@pytest.fixture
def copy_sessions(
    tmp_path: Path,
) -> Generator[sessionmaker[Session], None, None]:
    database = tmp_path / "qwen-copy-handler.db"
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
        qwen_api_key="fake-copy-handler-key",
        enable_copy_execution=True,
    )


def create_sources(
    sessions: sessionmaker[Session],
) -> tuple[int, int, int, str]:
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
            platforms=["TikTok", "Instagram", "Facebook"],
            tone="Clear and practical",
            objective="Build awareness",
        )
        strategy = MarketingStrategy(
            product_id=product.id,
            positioning="Portable wellness",
            audience_insights=["Busy professionals"],
            angles=["Fresh drinks anywhere"],
            risks=["No unsupported claims"],
            evidence=["Portable and rechargeable"],
        )
        session.add_all([brief, strategy])
        session.commit()
        preflight = CopyPreflightService(
            session, settings()
        ).run(brief.id, strategy.id)
        return product.id, brief.id, strategy.id, preflight.input_digest


def create_job(
    sessions: sessionmaker[Session],
    *,
    product_id: int,
    brief_id: int,
    strategy_id: int,
    digest: str,
    suffix: str,
    preflight_strategy_id: int | None = None,
) -> int:
    payload = QwenCopyMatrixGenerateV1Input(
        product_id=product_id,
        marketing_brief_id=brief_id,
        marketing_strategy_id=strategy_id,
        preflight_product_id=product_id,
        preflight_marketing_brief_id=brief_id,
        preflight_marketing_strategy_id=preflight_strategy_id or strategy_id,
        frozen_digest=digest,
    )
    with sessions() as session:
        created = ExecutionQueueService(session).create(
            ExecutionJobCreate(
                job_type=QWEN_COPY_MATRIX_GENERATE_V1,
                source_type="marketing_strategy",
                source_id=strategy_id,
                input_digest=hashlib.sha256(
                    json.dumps(payload.model_dump(), sort_keys=True).encode()
                ).hexdigest(),
                idempotency_key=f"qwen-copy-handler-{suffix}",
                input_payload=payload.model_dump(),
                concurrency_key=f"qwen-copy-product-{product_id}",
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
        QwenCopyMatrixGenerateV1Handler(
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


def test_fake_qwen_success_persists_exact_copy_result(
    copy_sessions: sessionmaker[Session],
) -> None:
    product_id, brief_id, strategy_id, digest = create_sources(copy_sessions)
    provider = FakeQwenProvider()
    job_id = create_job(
        copy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        strategy_id=strategy_id,
        digest=digest,
        suffix="success",
    )

    result = make_worker(copy_sessions, provider, "copy-worker-success").run_once()

    assert result.status == WorkerRunStatus.SUCCEEDED
    assert provider.calls == 1
    with copy_sessions() as session:
        assert session.scalar(select(func.count(CopyMatrix.id))) == 1
        job = ExecutionQueueService(session).get(job_id)
        assert job.result_entity_type == "copy_matrix"
        assert job.result_entity_id is not None
        matrix = session.get(CopyMatrix, job.result_entity_id)
        assert matrix is not None
        assert matrix.marketing_strategy_id == strategy_id
        assert [item["platform"] for item in matrix.copies] == [
            "TikTok",
            "Instagram",
            "Facebook",
        ]
        assert job.attempts[0].provider_call_count == 1
        assert job.attempts[0].external_submission_possible is True


def test_two_workers_generate_only_one_copy_matrix(
    copy_sessions: sessionmaker[Session],
) -> None:
    product_id, brief_id, strategy_id, digest = create_sources(copy_sessions)
    provider = FakeQwenProvider()
    create_job(
        copy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        strategy_id=strategy_id,
        digest=digest,
        suffix="concurrent",
    )
    barrier = threading.Barrier(3)
    results = []

    def run(worker_id: str) -> None:
        worker = make_worker(copy_sessions, provider, worker_id)
        barrier.wait()
        results.append(worker.run_once())

    threads = [
        threading.Thread(target=run, args=(f"copy-worker-{index}",))
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
    with copy_sessions() as session:
        assert session.scalar(select(func.count(CopyMatrix.id))) == 1


@pytest.mark.parametrize("change", ["relationship", "digest"])
def test_changed_source_fails_before_provider_and_can_retry(
    copy_sessions: sessionmaker[Session], change: str
) -> None:
    product_id, brief_id, strategy_id, digest = create_sources(copy_sessions)
    job_id = create_job(
        copy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        strategy_id=strategy_id,
        digest=digest,
        suffix=f"changed-{change}",
    )
    with copy_sessions() as session:
        if change == "relationship":
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
        else:
            session.get(Product, product_id).description = "Changed input"
        session.commit()
    provider = FakeQwenProvider()

    result = make_worker(
        copy_sessions, provider, f"copy-worker-{change}"
    ).run_once()

    assert result.status == WorkerRunStatus.FAILED
    assert provider.calls == 0
    with copy_sessions() as session:
        job = ExecutionQueueService(session).get(job_id)
        assert job.uncertain is False
        retried = ExecutionQueueService(session).retry(
            job_id, ExecutionJobRetryRequest(retry_confirmed=True)
        )
        assert retried.status == "QUEUED"


def test_provider_exception_is_submit_unknown_and_not_retryable(
    copy_sessions: sessionmaker[Session],
) -> None:
    product_id, brief_id, strategy_id, digest = create_sources(copy_sessions)
    provider = FakeQwenProvider(error=RuntimeError("uncertain fake transport"))
    job_id = create_job(
        copy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        strategy_id=strategy_id,
        digest=digest,
        suffix="uncertain",
    )

    result = make_worker(
        copy_sessions, provider, "copy-worker-uncertain"
    ).run_once()

    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert provider.calls == 1
    with copy_sessions() as session:
        job = ExecutionQueueService(session).get(job_id)
        assert job.uncertain is True
        with pytest.raises(AppError, match="Only certain failed jobs"):
            ExecutionQueueService(session).retry(
                job_id, ExecutionJobRetryRequest(retry_confirmed=True)
            )


def test_payload_and_error_fields_are_secret_free(
    copy_sessions: sessionmaker[Session],
) -> None:
    product_id, brief_id, strategy_id, digest = create_sources(copy_sessions)
    job_id = create_job(
        copy_sessions,
        product_id=product_id,
        brief_id=brief_id,
        strategy_id=strategy_id,
        digest=digest,
        suffix="secret-safe",
        preflight_strategy_id=strategy_id + 1,
    )
    provider = FakeQwenProvider()
    make_worker(copy_sessions, provider, "copy-worker-secret-safe").run_once()

    with copy_sessions() as session:
        job = session.get(ExecutionJob, job_id)
        serialized = json.dumps(
            {
                "payload": job.input_payload,
                "safe_error_code": job.safe_error_code,
                "safe_error_details": job.safe_error_details,
            }
        ).casefold()
    assert provider.calls == 0
    for forbidden in (
        "fake-copy-handler-key",
        "api_key",
        "authorization",
        "cookie",
        "token",
        "secret",
    ):
        assert forbidden not in serialized
