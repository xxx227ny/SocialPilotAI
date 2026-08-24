from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import (
    BatchVideoJob,
    BatchVideoVariant,
    BrandKit,
    BrandKitVersion,
    ExecutionAttempt,
    ExecutionJob,
    Product,
)
from app.schemas.batch_video import BatchVideoCreateRequest, BatchVideoRequest
from app.schemas.execution import ExecutionJobClaimRequest, ExecutionJobCompleteRequest
from app.services.batch_video_job_service import BatchVideoJobService
from app.services.batch_video_preflight import BatchVideoPreflightService
from app.services.execution_queue_service import ExecutionQueueService


def _products(session) -> list[Product]:
    products = [
        Product(
            name=f"Product {index}",
            category="Test",
            description="Provider-free queue evidence",
            selling_points=["Stable"],
            target_markets=["CN"],
        )
        for index in range(3)
    ]
    session.add_all(products)
    session.commit()
    return products


def _submit(
    session,
    ids: list[int],
    key: str = "batch-queue-e2e",
    *,
    max_concurrency: int = 3,
):
    request = BatchVideoRequest(
        product_ids=ids,
        platforms=["youtube", "tiktok", "instagram"],
        variants_per_platform=2,
        language="zh-CN",
        max_concurrency=max_concurrency,
        idempotency_key=key,
    )
    checked = BatchVideoPreflightService(session).run(request)
    return BatchVideoJobService(session).create(
        BatchVideoCreateRequest(
            **request.model_dump(),
            request_digest=checked.request_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            cost_confirmed=True,
        )
    )


def test_exact_expansion_idempotency_worker_and_provider_free(tmp_path: Path) -> None:
    database = tmp_path / "batch.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        ids = [item.id for item in _products(session)]
        first = _submit(session, ids)
        second = _submit(session, ids)
        assert first.reused is False and second.reused is True
        assert first.batch.id == second.batch.id
        assert [item.id for item in first.variants] == [
            item.id for item in second.variants
        ]
        assert session.query(BatchVideoJob).count() == 1
        assert session.query(BatchVideoVariant).count() == 18
        assert session.query(ExecutionJob).count() == 18
        assert len({job.concurrency_key for job in session.query(ExecutionJob)}) == 3
        batch = session.query(BatchVideoJob).one()
        assert batch.qwen_script_call_quota == 18
        assert batch.qwen_script_calls_reserved == 0
        assert first.batch.qwen_script_call_quota == 18
        assert first.batch.qwen_script_calls_reserved == 0

    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=Settings(
            _env_file=None,
            database_url=f"sqlite:///{database.as_posix()}",
            video_artifact_storage_root=str(tmp_path / "unused-artifacts"),
        ),
    )
    workers = [
        ExecutionWorker(
            session_factory=sessions,
            registry=registry,
            worker_id=f"batch-worker-{index:02d}",
            lease_seconds=30,
            heartbeat_interval_seconds=1,
        )
        for index in range(18)
    ]
    results = []
    for offset in range(0, 18, 3):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results.extend(
                pool.map(lambda worker: worker.run_once(), workers[offset : offset + 3])
            )
    assert all(result.status == WorkerRunStatus.SUCCEEDED for result in results)
    assert workers[0].run_once().status == WorkerRunStatus.NO_JOB

    with sessions() as session:
        variants = session.query(BatchVideoVariant).order_by(BatchVideoVariant.id).all()
        jobs = session.query(ExecutionJob).order_by(ExecutionJob.id).all()
        assert [item.id for item in variants] == list(range(1, 19))
        assert all(item.status == "READY_FOR_SCRIPT" for item in variants)
        assert all(job.status == "SUCCEEDED" for job in jobs)
        assert all(job.provider_name == "local_batch_orchestrator" for job in jobs)
        assert [job.result_entity_id for job in jobs] == list(range(1, 19))
        assert session.query(ExecutionAttempt).count() == 18
        assert (
            sum(item.provider_call_count for item in session.query(ExecutionAttempt))
            == 0
        )
    engine.dispose()


def test_atomic_rollback_when_child_creation_fails(db_session, monkeypatch) -> None:
    ids = [item.id for item in _products(db_session)]
    original = db_session.flush
    calls = 0

    def fail_midway(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise RuntimeError("injected atomic failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_midway)
    with pytest.raises(RuntimeError, match="injected atomic failure"):
        _submit(db_session, ids)
    monkeypatch.setattr(db_session, "flush", original)
    assert db_session.query(BatchVideoJob).count() == 0
    assert db_session.query(BatchVideoVariant).count() == 0
    assert db_session.query(ExecutionJob).count() == 0


def test_two_sessions_converge_on_one_batch(tmp_path: Path) -> None:
    database = tmp_path / "batch-race.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        ids = [item.id for item in _products(session)]
        request = BatchVideoRequest(
            product_ids=ids,
            platforms=["youtube", "tiktok", "instagram"],
            variants_per_platform=2,
            language="zh-CN",
            max_concurrency=3,
            idempotency_key="batch-two-session-race",
        )
        checked = BatchVideoPreflightService(session).run(request)
        data = BatchVideoCreateRequest(
            **request.model_dump(),
            request_digest=checked.request_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            cost_confirmed=True,
        )

    def submit():
        with sessions() as session:
            return BatchVideoJobService(session).create(data)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results[0].batch.id == results[1].batch.id
    assert sorted(item.reused for item in results) == [False, True]
    with sessions() as session:
        assert session.query(BatchVideoJob).count() == 1
        assert session.query(BatchVideoVariant).count() == 18
        assert session.query(ExecutionJob).count() == 18
    engine.dispose()


def test_one_real_worker_failure_does_not_block_other_seventeen(
    tmp_path: Path,
) -> None:
    database = tmp_path / "batch-one-failure.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        kit = BrandKit(name="Failure isolation brand")
        session.add(kit)
        session.flush()
        version = BrandKitVersion(
            brand_kit_id=kit.id,
            version_number=1,
            digest="a" * 64,
            brand_name="Frozen A",
            positioning="Stable",
            default_language="zh-CN",
            brand_tone="Clear",
            preferred_terms=[],
            forbidden_terms=[],
            target_regions=[],
            audience_guidelines=[],
            visual_guidelines=[],
            required_disclosures=[],
            claims_constraints=[],
        )
        session.add(version)
        session.flush()
        products = _products(session)
        products[0].brand_kit_version_id = version.id
        session.commit()
        created = _submit(session, [item.id for item in products])
        failed_variant_id = created.variants[0].id
        failed_variant = session.get(BatchVideoVariant, failed_variant_id)
        failed_variant.brand_kit_version_digest = "b" * 64
        session.commit()

    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=Settings(
            _env_file=None,
            database_url=f"sqlite:///{database.as_posix()}",
            video_artifact_storage_root=str(tmp_path / "unused-failure-artifacts"),
        ),
    )
    worker = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="batch-failure-worker",
        lease_seconds=30,
        heartbeat_interval_seconds=1,
    )
    results = [worker.run_once() for _ in range(18)]
    statuses = [item.status for item in results]
    assert statuses.count(WorkerRunStatus.FAILED) == 1
    assert statuses.count(WorkerRunStatus.SUCCEEDED) == 17
    assert worker.run_once().status == WorkerRunStatus.NO_JOB
    with sessions() as session:
        jobs = session.query(ExecutionJob).order_by(ExecutionJob.id).all()
        attempts = session.query(ExecutionAttempt).order_by(ExecutionAttempt.id).all()
        variants = session.query(BatchVideoVariant).order_by(BatchVideoVariant.id).all()
        failed_jobs = [item for item in jobs if item.status == "FAILED"]
        assert len(failed_jobs) == 1
        assert failed_jobs[0].source_id == failed_variant_id
        assert failed_jobs[0].safe_error_code == "BATCH_VARIANT_BRAND_MISMATCH"
        assert [item.attempt_count for item in jobs] == [1] * 18
        assert len(attempts) == 18
        assert sum(item.status == "FAILED" for item in attempts) == 1
        assert sum(item.status == "SUCCEEDED" for item in attempts) == 17
        assert sum(item.provider_call_count for item in attempts) == 0
        ready = [item for item in variants if item.status == "READY_FOR_SCRIPT"]
        assert len(ready) == 17
        assert all(
            job.result_entity_id == job.source_id
            for job in jobs
            if job.status == "SUCCEEDED"
        )
        assert BatchVideoJobService(session).get_batch(created.batch.id).status == (
            "PARTIAL_FAILED"
        )
    engine.dispose()


def test_product_rebind_keeps_frozen_brand_identity_for_real_workers(
    tmp_path: Path,
) -> None:
    database = tmp_path / "batch-brand-rebind.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        kit = BrandKit(name="Rebind brand")
        session.add(kit)
        session.flush()
        versions = [
            BrandKitVersion(
                brand_kit_id=kit.id,
                version_number=index,
                digest=character * 64,
                brand_name=f"Frozen {character}",
                positioning="Stable",
                default_language="zh-CN",
                brand_tone="Clear",
                preferred_terms=[],
                forbidden_terms=[],
                target_regions=[],
                audience_guidelines=[],
                visual_guidelines=[],
                required_disclosures=[],
                claims_constraints=[],
            )
            for index, character in ((1, "a"), (2, "b"))
        ]
        session.add_all(versions)
        session.flush()
        products = _products(session)
        for product in products:
            product.brand_kit_version_id = versions[0].id
        session.commit()
        created = _submit(session, [item.id for item in products], "batch-brand-rebind")
        request_digest = created.batch.request_digest
        source_digests = [item.source_digest for item in created.variants]
        for product in products:
            product.brand_kit_version_id = versions[1].id
        session.commit()

    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=Settings(
            _env_file=None,
            database_url=f"sqlite:///{database.as_posix()}",
            video_artifact_storage_root=str(tmp_path / "unused-rebind-artifacts"),
        ),
    )
    worker = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="batch-rebind-worker",
        lease_seconds=30,
        heartbeat_interval_seconds=1,
    )
    assert all(worker.run_once().status == WorkerRunStatus.SUCCEEDED for _ in range(18))
    with sessions() as session:
        restored = BatchVideoJobService(session).get_batch(created.batch.id)
        variants = BatchVideoJobService(session).list_variants(created.batch.id)
        assert restored.request_digest == request_digest
        assert [item.source_digest for item in variants] == source_digests
        assert {item.brand_kit_version_id for item in variants} == {versions[0].id}
        assert {item.brand_kit_version_digest for item in variants} == {"a" * 64}
        assert {
            session.get(Product, item.product_id).brand_kit_version_id
            for item in variants
        } == {versions[1].id}
        assert all(item.status == "READY_FOR_SCRIPT" for item in variants)
        assert (
            sum(
                attempt.provider_call_count
                for attempt in session.query(ExecutionAttempt).all()
            )
            == 0
        )
    engine.dispose()


def test_batch_concurrency_limit_holds_real_leases_without_sleep(
    tmp_path: Path,
) -> None:
    database = tmp_path / "batch-concurrency-limit.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        products = _products(session)
        first = _submit(
            session,
            [item.id for item in products],
            "batch-concurrency-first",
            max_concurrency=3,
        )
        jobs = session.query(ExecutionJob).order_by(ExecutionJob.id).all()
        assert [job.concurrency_key for job in jobs] == [
            f"video-batch:{first.batch.id}:slot:{index % 3}" for index in range(18)
        ]
    claimed = []
    for index in range(3):
        with sessions() as session:
            item = ExecutionQueueService(session).claim(
                ExecutionJobClaimRequest(
                    worker_id=f"batch-slot-worker-{index}",
                    lease_seconds=60,
                    job_types=["video.batch.variant.prepare.v1"],
                )
            )
            assert item is not None and item.lease_active
            claimed.append(item)
    with sessions() as session:
        assert (
            ExecutionQueueService(session).claim(
                ExecutionJobClaimRequest(
                    worker_id="batch-slot-worker-overflow",
                    lease_seconds=60,
                    job_types=["video.batch.variant.prepare.v1"],
                )
            )
            is None
        )
        second_products = _products(session)
        second = _submit(
            session,
            [item.id for item in second_products],
            "batch-concurrency-second",
            max_concurrency=1,
        )
    with sessions() as session:
        other = ExecutionQueueService(session).claim(
            ExecutionJobClaimRequest(
                worker_id="batch-second-independent",
                lease_seconds=60,
                job_types=["video.batch.variant.prepare.v1"],
            )
        )
        assert other is not None
        assert session.get(BatchVideoVariant, other.source_id).batch_video_job_id == (
            second.batch.id
        )
    with sessions() as session:
        ExecutionQueueService(session).complete(
            claimed[0].id,
            ExecutionJobCompleteRequest(
                worker_id="batch-slot-worker-0", provider_call_count=0
            ),
        )
    with sessions() as session:
        released = ExecutionQueueService(session).claim(
            ExecutionJobClaimRequest(
                worker_id="batch-slot-worker-released",
                lease_seconds=60,
                job_types=["video.batch.variant.prepare.v1"],
            )
        )
        assert released is not None
        assert session.get(
            BatchVideoVariant, released.source_id
        ).batch_video_job_id == (first.batch.id)
    engine.dispose()
