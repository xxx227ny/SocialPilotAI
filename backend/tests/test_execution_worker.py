from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import AppError
from app.db.base import Base
from app.execution.contracts import ExecutionContext, HandlerResult
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunResult, WorkerRunStatus
from app.models.execution import ExecutionAttempt, ExecutionJob
from app.schemas.execution import (
    ExecutionJobCompleteRequest,
    ExecutionJobCreate,
    ExecutionJobRetryRequest,
)
from app.services.execution_queue_service import ExecutionQueueService


class FakeInput(BaseModel):
    value: str


class FakeHandler:
    input_schema = FakeInput

    def __init__(
        self,
        job_type: str,
        execute: Callable[[ExecutionContext, FakeInput], HandlerResult],
    ) -> None:
        self.job_type = job_type
        self._execute = execute
        self.calls = 0

    def execute(
        self, context: ExecutionContext, payload: BaseModel
    ) -> HandlerResult:
        self.calls += 1
        return self._execute(context, FakeInput.model_validate(payload))


@pytest.fixture
def worker_sessions(
    tmp_path: Path,
) -> Generator[sessionmaker[Session], None, None]:
    database = tmp_path / "execution-worker.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    yield sessions
    engine.dispose()


def job_data(
    label: str,
    job_type: str,
    *,
    concurrency_key: str | None = None,
    payload: dict[str, object] | None = None,
) -> ExecutionJobCreate:
    return ExecutionJobCreate(
        job_type=job_type,
        source_type="product",
        source_id=1,
        input_digest=hashlib.sha256(label.encode()).hexdigest(),
        idempotency_key=f"worker-stage1d2a-{label}",
        input_payload=payload or {"value": label},
        concurrency_key=concurrency_key,
        max_attempts=2,
    )


def create_job(
    sessions: sessionmaker[Session], data: ExecutionJobCreate
) -> int:
    with sessions() as session:
        return ExecutionQueueService(session).create(data).job.id


def get_job(sessions: sessionmaker[Session], job_id: int) -> ExecutionJob:
    with sessions() as session:
        job = ExecutionQueueService(session).get(job_id)
        session.expunge_all()
        return job


def worker(
    sessions: sessionmaker[Session],
    registry: ExecutionHandlerRegistry,
    worker_id: str = "worker-stage1d2a",
) -> ExecutionWorker:
    return ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id=worker_id,
        lease_seconds=5,
        heartbeat_interval_seconds=0.05,
    )


def registry_with(handler: FakeHandler) -> ExecutionHandlerRegistry:
    registry = ExecutionHandlerRegistry()
    registry.register(handler)
    return registry


def test_success_handler_completes_owned_job(
    worker_sessions: sessionmaker[Session],
) -> None:
    handler = FakeHandler(
        "fake.success",
        lambda context, _: (
            context.before_provider_call(may_submit_external=False),
            HandlerResult.succeeded(
                provider_name="fake", provider_operation_id="fake-operation"
            ),
        )[1],
    )
    job_id = create_job(worker_sessions, job_data("success", handler.job_type))
    result = worker(worker_sessions, registry_with(handler)).run_once()

    assert result == WorkerRunResult(WorkerRunStatus.SUCCEEDED, job_id)
    job = get_job(worker_sessions, job_id)
    assert job.status == "SUCCEEDED"
    assert job.uncertain is False
    assert job.attempts[0].provider_call_count == 1
    assert job.attempts[0].status == "SUCCEEDED"
    assert handler.calls == 1


def test_pre_submission_failure_is_deterministic_failed(
    worker_sessions: sessionmaker[Session],
) -> None:
    handler = FakeHandler(
        "fake.pre-failure",
        lambda *_: HandlerResult.failed(
            "FAKE_PRE_SUBMISSION_FAILURE", safe_error_details={"phase": "local"}
        ),
    )
    job_id = create_job(worker_sessions, job_data("pre-failure", handler.job_type))
    result = worker(worker_sessions, registry_with(handler)).run_once()

    assert result.status == WorkerRunStatus.FAILED
    job = get_job(worker_sessions, job_id)
    assert job.status == "FAILED"
    assert job.uncertain is False
    assert job.safe_error_code == "FAKE_PRE_SUBMISSION_FAILURE"
    assert job.attempts[0].external_submission_possible is False


def test_exception_after_submission_boundary_is_submit_unknown_and_not_retried(
    worker_sessions: sessionmaker[Session],
) -> None:
    def uncertain(context: ExecutionContext, _: FakeInput) -> HandlerResult:
        context.before_provider_call(may_submit_external=True)
        raise RuntimeError("fake provider response must not be persisted")

    handler = FakeHandler("fake.uncertain", uncertain)
    job_id = create_job(worker_sessions, job_data("uncertain", handler.job_type))
    result = worker(worker_sessions, registry_with(handler)).run_once()

    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    job = get_job(worker_sessions, job_id)
    assert job.status == "SUBMIT_UNKNOWN"
    assert job.uncertain is True
    assert job.safe_error_code == "HANDLER_EXECUTION_UNCERTAIN"
    assert job.attempts[0].provider_call_count == 1
    assert job.attempts[0].external_submission_possible is True
    assert "fake provider response" not in str(job.safe_error_details)
    with worker_sessions() as session, pytest.raises(AppError):
        ExecutionQueueService(session).retry(
            job_id, ExecutionJobRetryRequest(retry_confirmed=True)
        )


def test_unregistered_type_and_invalid_input_fail_without_uncertainty(
    worker_sessions: sessionmaker[Session],
) -> None:
    unknown_id = create_job(
        worker_sessions, job_data("unknown", "fake.not-registered")
    )
    empty_registry = ExecutionHandlerRegistry()
    unknown_result = worker(worker_sessions, empty_registry).run_once()
    assert unknown_result.status == WorkerRunStatus.FAILED
    unknown = get_job(worker_sessions, unknown_id)
    assert unknown.safe_error_code == "UNREGISTERED_JOB_TYPE"
    assert unknown.uncertain is False

    handler = FakeHandler("fake.validation", lambda *_: HandlerResult.succeeded())
    invalid_id = create_job(
        worker_sessions,
        job_data(
            "validation",
            handler.job_type,
            payload={"wrong_field": "missing value"},
        ),
    )
    invalid_result = worker(worker_sessions, registry_with(handler)).run_once()
    assert invalid_result.status == WorkerRunStatus.FAILED
    invalid = get_job(worker_sessions, invalid_id)
    assert invalid.safe_error_code == "INVALID_JOB_INPUT"
    assert handler.calls == 0


def test_heartbeat_renews_lease_and_thread_is_joined(
    worker_sessions: sessionmaker[Session],
) -> None:
    started = threading.Event()
    release = threading.Event()

    def wait_for_release(
        context: ExecutionContext, _: FakeInput
    ) -> HandlerResult:
        started.set()
        while not release.is_set():
            context.wait(0.02)
        return HandlerResult.succeeded()

    handler = FakeHandler("fake.heartbeat", wait_for_release)
    job_id = create_job(worker_sessions, job_data("heartbeat", handler.job_type))
    execution_worker = worker(worker_sessions, registry_with(handler))
    result_holder: list[WorkerRunResult] = []
    run_thread = threading.Thread(
        target=lambda: result_holder.append(execution_worker.run_once())
    )
    run_thread.start()
    assert started.wait(timeout=5)
    with worker_sessions() as session:
        first_expiry = session.get(ExecutionJob, job_id).lease_expires_at
    time.sleep(0.15)
    with worker_sessions() as session:
        second_expiry = session.get(ExecutionJob, job_id).lease_expires_at
    assert first_expiry is not None and second_expiry is not None
    assert second_expiry > first_expiry
    release.set()
    run_thread.join(timeout=5)

    assert not run_thread.is_alive()
    assert result_holder[0].status == WorkerRunStatus.SUCCEEDED
    assert execution_worker.has_live_heartbeat is False
    assert not any(
        thread.name == f"execution-heartbeat-{job_id}"
        for thread in threading.enumerate()
    )


def test_lost_lease_cannot_overwrite_replacement_owner_result(
    worker_sessions: sessionmaker[Session],
) -> None:
    started = threading.Event()
    release = threading.Event()

    def ignore_context_after_start(
        _: ExecutionContext, __: FakeInput
    ) -> HandlerResult:
        started.set()
        assert release.wait(timeout=5)
        return HandlerResult.succeeded(provider_name="stale-worker")

    handler = FakeHandler("fake.lease-lost", ignore_context_after_start)
    job_id = create_job(worker_sessions, job_data("lease-lost", handler.job_type))
    execution_worker = worker(
        worker_sessions, registry_with(handler), worker_id="worker-original"
    )
    result_holder: list[WorkerRunResult] = []
    run_thread = threading.Thread(
        target=lambda: result_holder.append(execution_worker.run_once())
    )
    run_thread.start()
    assert started.wait(timeout=5)

    replacement_id = "worker-replacement"
    replacement_digest = hashlib.sha256(replacement_id.encode()).hexdigest()
    with worker_sessions() as session:
        session.execute(
            update(ExecutionJob)
            .where(ExecutionJob.id == job_id)
            .values(lease_owner_digest=replacement_digest)
        )
        session.commit()
    time.sleep(0.1)
    release.set()
    run_thread.join(timeout=5)

    assert result_holder[0].status == WorkerRunStatus.LEASE_LOST
    with worker_sessions() as session:
        service = ExecutionQueueService(session)
        completed = service.complete(
            job_id,
            ExecutionJobCompleteRequest(
                worker_id=replacement_id,
                provider_name="replacement",
                provider_call_count=0,
            ),
        )
        assert completed.status == "SUCCEEDED"
    job = get_job(worker_sessions, job_id)
    assert job.provider_name == "replacement"
    assert job.provider_name != "stale-worker"
    assert execution_worker.has_live_heartbeat is False


def test_safe_stop_finishes_job_and_leaves_no_heartbeat_thread(
    worker_sessions: sessionmaker[Session],
) -> None:
    started = threading.Event()

    def cooperative_handler(
        context: ExecutionContext, _: FakeInput
    ) -> HandlerResult:
        started.set()
        while True:
            context.wait(0.02)

    handler = FakeHandler("fake.stop", cooperative_handler)
    job_id = create_job(worker_sessions, job_data("stop", handler.job_type))
    execution_worker = worker(worker_sessions, registry_with(handler))
    result_holder: list[WorkerRunResult] = []
    run_thread = threading.Thread(
        target=lambda: result_holder.append(execution_worker.run_once())
    )
    run_thread.start()
    assert started.wait(timeout=5)
    execution_worker.stop()
    run_thread.join(timeout=5)

    assert not run_thread.is_alive()
    assert result_holder[0].status == WorkerRunStatus.FAILED
    job = get_job(worker_sessions, job_id)
    assert job.status == "FAILED"
    assert job.safe_error_code == "WORKER_STOPPED"
    assert execution_worker.has_live_heartbeat is False
    assert execution_worker.run_once().status == WorkerRunStatus.STOPPED


def test_two_workers_respect_shared_concurrency_key(
    worker_sessions: sessionmaker[Session],
) -> None:
    entered = threading.Event()
    release = threading.Event()
    active = 0
    maximum_active = 0
    state_lock = threading.Lock()

    def guarded(context: ExecutionContext, _: FakeInput) -> HandlerResult:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        entered.set()
        try:
            while not release.is_set():
                context.wait(0.02)
            return HandlerResult.succeeded()
        finally:
            with state_lock:
                active -= 1

    handler = FakeHandler("fake.concurrency", guarded)
    first_id = create_job(
        worker_sessions,
        job_data(
            "concurrency-a", handler.job_type, concurrency_key="product:shared"
        ),
    )
    second_id = create_job(
        worker_sessions,
        job_data(
            "concurrency-b", handler.job_type, concurrency_key="product:shared"
        ),
    )
    registry = registry_with(handler)
    first_worker = worker(worker_sessions, registry, "worker-concurrency-a")
    second_worker = worker(worker_sessions, registry, "worker-concurrency-b")
    results: list[WorkerRunResult] = []
    threads = [
        threading.Thread(target=lambda: results.append(first_worker.run_once())),
        threading.Thread(target=lambda: results.append(second_worker.run_once())),
    ]
    for thread in threads:
        thread.start()
    assert entered.wait(timeout=5)
    time.sleep(0.1)
    release.set()
    for thread in threads:
        thread.join(timeout=5)

    assert maximum_active == 1
    assert sorted(result.status for result in results) == [
        WorkerRunStatus.NO_JOB,
        WorkerRunStatus.SUCCEEDED,
    ]
    with worker_sessions() as session:
        jobs = list(
            session.scalars(
                select(ExecutionJob).where(
                    ExecutionJob.id.in_([first_id, second_id])
                )
            )
        )
        assert [job.status for job in jobs].count("SUCCEEDED") == 1
        assert [job.status for job in jobs].count("QUEUED") == 1
        assert len(list(session.scalars(select(ExecutionAttempt)))) == 1


def test_registry_is_exact_and_rejects_duplicate_or_dynamic_types() -> None:
    handler = FakeHandler("fake.exact", lambda *_: HandlerResult.succeeded())
    registry = registry_with(handler)
    assert registry.resolve("fake.exact") is handler
    assert registry.resolve("fake") is None
    assert registry.resolve("FAKE.EXACT") is None
    with pytest.raises(ValueError, match="already registered"):
        registry.register(handler)
    invalid = FakeHandler("Fake Invalid", lambda *_: HandlerResult.succeeded())
    with pytest.raises(ValueError, match="exact normalized"):
        registry.register(invalid)


def test_unsafe_handler_error_details_are_never_persisted(
    worker_sessions: sessionmaker[Session],
) -> None:
    def unsafe_result(*_: object) -> HandlerResult:
        return HandlerResult.failed(
            "UNSAFE_RESULT", safe_error_details={"authorization": "not-stored"}
        )

    handler = FakeHandler("fake.unsafe", unsafe_result)
    job_id = create_job(worker_sessions, job_data("unsafe", handler.job_type))
    result = worker(worker_sessions, registry_with(handler)).run_once()
    assert result.status == WorkerRunStatus.FAILED
    job = get_job(worker_sessions, job_id)
    assert job.safe_error_code == "HANDLER_EXECUTION_FAILED"
    assert job.safe_error_details is None
    assert "not-stored" not in str(job.attempts[0].safe_error_details)
