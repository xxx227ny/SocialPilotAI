from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.base import Base
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import ExecutionAttempt, ExecutionJob, VideoCompositionEnhancement
from app.schemas.video_composition_enhancement import (
    VideoCompositionEnhancementSubmitRequest,
)
from app.services.video_composition_enhancement_job_service import (
    VideoCompositionEnhancementJobService,
)
from app.services.video_composition_enhancement_preflight import (
    VideoCompositionEnhancementPreflightService,
)
from tests.test_video_composition_enhancement import _request, _source


def _settings(root: Path, database: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{database.as_posix()}",
        enable_video_composition_enhancement=True,
        video_artifact_storage_root=str(root),
        video_composition_temp_root=str(root / "temp"),
    )


def test_two_sessions_and_two_workers_execute_enhancement_once(tmp_path) -> None:
    database = tmp_path / "queue.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = _settings(tmp_path, database)
    with sessions() as session:
        product, _, composition, source, voice, music = _source(session, tmp_path)
        request = _request(composition, source, voice, music)
        preflight = VideoCompositionEnhancementPreflightService(
            session, settings
        ).run(product.id, request)
        submit = VideoCompositionEnhancementSubmitRequest(
            **request.model_dump(),
            input_digest=preflight.input_digest,
            source_chain_digest=preflight.source_chain_digest,
            preflight_digest=preflight.preflight_digest,
            preflight_expires_at=preflight.expires_at,
            local_cpu_cost_confirmed=True,
        )
        product_id = product.id

    barrier = Barrier(2)

    def enqueue():
        with sessions() as session:
            barrier.wait()
            result = VideoCompositionEnhancementJobService(
                session, settings
            ).enqueue(product_id, submit)
            return result.enhancement.id, result.job.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: enqueue(), range(2)))
    assert responses[0] == responses[1]
    with sessions() as session:
        assert session.query(VideoCompositionEnhancement).count() == 1
        assert session.query(ExecutionJob).count() == 1

    calls = 0
    call_lock = Lock()

    def fake_enhance(_service, _enhancement_id, *, before_persist):
        nonlocal calls
        before_persist()
        with call_lock:
            calls += 1
        return SimpleNamespace(id=77)

    registry = build_execution_handler_registry(
        session_factory=sessions, settings=settings
    )
    workers = [
        ExecutionWorker(
            session_factory=sessions,
            registry=registry,
            worker_id=f"enhance-worker-{index}",
            lease_seconds=30,
            heartbeat_interval_seconds=1,
        )
        for index in range(2)
    ]
    with patch(
        "app.execution.handlers.video_composition_enhancement."
        "VideoCompositionEnhancementService.enhance",
        autospec=True,
        side_effect=fake_enhance,
    ), ThreadPoolExecutor(max_workers=2) as pool:
        worker_results = list(pool.map(lambda worker: worker.run_once(), workers))
    assert calls == 1
    assert sorted(result.status for result in worker_results) == sorted(
        [WorkerRunStatus.SUCCEEDED, WorkerRunStatus.NO_JOB]
    )
    with sessions() as session:
        job = session.query(ExecutionJob).one()
        assert job.status == "SUCCEEDED"
        assert job.result_entity_type == "video_composition_enhancement_artifact"
        assert job.result_entity_id == 77
        attempt = session.query(ExecutionAttempt).one()
        assert attempt.provider_call_count == 0
        assert attempt.external_submission_possible is True
    engine.dispose()


def test_persist_unknown_is_not_reexecuted_after_worker_restart(tmp_path) -> None:
    database = tmp_path / "unknown.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = _settings(tmp_path, database)
    with sessions() as session:
        product, _, composition, source, voice, music = _source(
            session,
            tmp_path,
        )
        request = _request(composition, source, voice, music)
        checked = VideoCompositionEnhancementPreflightService(
            session,
            settings,
        ).run(product.id, request)
        submit = VideoCompositionEnhancementSubmitRequest(
            **request.model_dump(),
            input_digest=checked.input_digest,
            source_chain_digest=checked.source_chain_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            local_cpu_cost_confirmed=True,
        )
        VideoCompositionEnhancementJobService(session, settings).enqueue(
            product.id,
            submit,
        )

    calls = 0

    def uncertain(_service, enhancement_id, *, before_persist):
        nonlocal calls
        calls += 1
        before_persist()
        enhancement = _service.session.get(
            VideoCompositionEnhancement,
            enhancement_id,
        )
        enhancement.status = "PERSIST_UNKNOWN"
        enhancement.safe_error_code = "ENHANCEMENT_RESULT_PERSIST_UNKNOWN"
        _service.session.commit()
        raise AppError("uncertain", 500)

    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=settings,
    )
    first_worker = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="enhance-unknown-first",
        lease_seconds=30,
        heartbeat_interval_seconds=1,
    )
    second_worker = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="enhance-unknown-restart",
        lease_seconds=30,
        heartbeat_interval_seconds=1,
    )
    with patch(
        "app.execution.handlers.video_composition_enhancement."
        "VideoCompositionEnhancementService.enhance",
        autospec=True,
        side_effect=uncertain,
    ):
        assert first_worker.run_once().status == WorkerRunStatus.SUBMIT_UNKNOWN
        assert second_worker.run_once().status == WorkerRunStatus.NO_JOB
    assert calls == 1
    with sessions() as session:
        job = session.query(ExecutionJob).one()
        enhancement = session.query(VideoCompositionEnhancement).one()
        assert job.status == "SUBMIT_UNKNOWN"
        assert job.uncertain is True
        assert enhancement.status == "PERSIST_UNKNOWN"
        assert session.query(ExecutionAttempt).count() == 1
    engine.dispose()
