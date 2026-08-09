from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateIndex

import app.services.database_migration_service as migration_service
from app.api.dependencies import (
    get_text_generation_provider,
    get_visual_generation_provider,
    get_youtube_provider,
)
from app.core.exceptions import AppError
from app.db.base import Base
from app.main import app
from app.models.execution import ExecutionAttempt, ExecutionJob
from app.models.product import utc_now
from app.schemas.execution import (
    ExecutionJobClaimRequest,
    ExecutionJobCompleteRequest,
    ExecutionJobCreate,
    ExecutionJobFailRequest,
    ExecutionJobHeartbeatRequest,
    ExecutionJobRetryRequest,
    ExecutionJobUnknownRequest,
)
from app.services.execution_queue_service import ExecutionQueueService


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def create_data(
    label: str,
    *,
    priority: int = 0,
    estimated_cost: str = "0",
    cost_confirmed: bool = False,
    max_attempts: int = 2,
    concurrency_key: str | None = None,
) -> ExecutionJobCreate:
    return ExecutionJobCreate(
        job_type="copy.variant",
        source_type="product",
        source_id=1,
        input_digest=digest(label),
        idempotency_key=f"stage1d1-{label}",
        input_payload={"label": label, "options": ["safe"]},
        priority=priority,
        concurrency_key=concurrency_key,
        estimated_cost=estimated_cost,
        cost_confirmed=cost_confirmed,
        max_attempts=max_attempts,
    )


def claim_data(worker: str = "worker-alpha") -> ExecutionJobClaimRequest:
    return ExecutionJobClaimRequest(worker_id=worker, lease_seconds=60)


def test_idempotent_reuse_and_digest_conflict(db_session: Session) -> None:
    service = ExecutionQueueService(db_session)
    first = service.create(create_data("same-key"))
    reused = service.create(create_data("same-key"))
    assert reused.reused is True
    assert reused.job.id == first.job.id

    conflicting = create_data("different-input").model_copy(
        update={"idempotency_key": "stage1d1-same-key"}
    )
    with pytest.raises(AppError) as captured:
        service.create(conflicting)
    assert getattr(captured.value, "status_code", None) == 409
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 1


def test_api_rejects_sensitive_payload_without_echo_or_write(
    client: TestClient, db_session: Session
) -> None:
    payload = create_data("sensitive").model_dump(mode="json")
    payload["input_payload"] = {"nested": {"authorization": "do-not-echo"}}
    response = client.post("/api/v1/execution-jobs", json=payload)
    assert response.status_code == 422
    assert "do-not-echo" not in response.text
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 0


def test_sensitive_error_details_are_rejected_without_echo_or_state_change(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/execution-jobs",
        json=create_data("sensitive-error").model_dump(mode="json"),
    ).json()["job"]
    claim = client.post(
        "/api/v1/execution-jobs/claim",
        json=claim_data("worker-sensitive").model_dump(),
    )
    assert claim.status_code == 200
    response = client.post(
        f"/api/v1/execution-jobs/{created['id']}/fail",
        json={
            "worker_id": "worker-sensitive",
            "safe_error_code": "SAFE_FAILURE",
            "safe_error_details": {"cookie": "do-not-echo-error"},
        },
    )
    assert response.status_code == 422
    assert "do-not-echo-error" not in response.text
    restored = client.get(f"/api/v1/execution-jobs/{created['id']}").json()
    assert restored["status"] == "RUNNING"
    assert restored["safe_error_details"] is None


def test_priority_cost_confirmation_and_concurrency_order(
    db_session: Session,
) -> None:
    service = ExecutionQueueService(db_session)
    blocked = service.create(
        create_data("cost-blocked", priority=100, estimated_cost="1.25")
    ).job
    high = service.create(
        create_data("high", priority=20, concurrency_key="product:1")
    ).job
    low = service.create(create_data("low", priority=1)).job

    first = service.claim(claim_data("worker-high"))
    assert first is not None and first.id == high.id
    second = service.claim(claim_data("worker-low"))
    assert second is not None and second.id == low.id
    assert service.claim(claim_data("worker-none")) is None
    assert service.get(blocked.id).status == "QUEUED"

    other = service.create(
        create_data("same-concurrency", priority=50, concurrency_key="product:1")
    ).job
    assert service.claim(claim_data("worker-concurrency")) is None
    service.complete(
        high.id,
        ExecutionJobCompleteRequest(
            worker_id="worker-high", provider_call_count=0
        ),
    )
    claimed_other = service.claim(claim_data("worker-concurrency"))
    assert claimed_other is not None and claimed_other.id == other.id


def test_pause_resume_cancel_and_running_actions_are_safe(
    db_session: Session,
) -> None:
    service = ExecutionQueueService(db_session)
    job = service.create(create_data("lifecycle")).job
    assert service.pause(job.id).status == "PAUSED"
    assert service.claim(claim_data()) is None
    assert service.resume(job.id).status == "QUEUED"
    running = service.claim(claim_data())
    assert running is not None and running.status == "RUNNING"
    with pytest.raises(AppError) as pause_error:
        service.pause(job.id)
    assert getattr(pause_error.value, "status_code", None) == 409
    with pytest.raises(AppError) as cancel_error:
        service.cancel(job.id)
    assert getattr(cancel_error.value, "status_code", None) == 409

    cancellable = service.create(create_data("cancel")).job
    assert service.cancel(cancellable.id).status == "CANCELLED"


def test_heartbeat_requires_owner_and_records_only_digest(
    db_session: Session,
) -> None:
    service = ExecutionQueueService(db_session)
    job = service.create(create_data("heartbeat")).job
    claimed = service.claim(claim_data("worker-owner"))
    assert claimed is not None
    assert claimed.lease_active is True
    internal = db_session.get(ExecutionJob, job.id)
    assert internal is not None
    assert internal.lease_owner_digest == digest("worker-owner")
    assert "lease_owner_digest" not in claimed.model_dump()
    assert "lease_expires_at" not in claimed.model_dump()
    assert "worker-owner" not in json.dumps(claimed.model_dump(), default=str)
    assert digest("worker-owner") not in json.dumps(
        claimed.model_dump(), default=str
    )
    with pytest.raises(AppError) as captured:
        service.heartbeat(
            job.id,
            ExecutionJobHeartbeatRequest(
                worker_id="worker-other", lease_seconds=60
            ),
        )
    assert getattr(captured.value, "status_code", None) == 409
    updated = service.heartbeat(
        job.id,
        ExecutionJobHeartbeatRequest(
            worker_id="worker-owner",
            lease_seconds=120,
            provider_call_count=1,
        ),
    )
    assert updated.attempts[0].provider_call_count == 1


def test_expired_safe_lease_requeues_but_external_becomes_unknown(
    db_session: Session,
) -> None:
    service = ExecutionQueueService(db_session)
    safe = service.create(create_data("safe-expiry", max_attempts=2)).job
    assert service.claim(claim_data("worker-safe")) is not None
    db_session.execute(
        update(ExecutionJob)
        .where(ExecutionJob.id == safe.id)
        .values(lease_expires_at=utc_now() - timedelta(seconds=1))
    )
    db_session.commit()
    recovered = service.recover_expired_leases()
    assert [item.id for item in recovered] == [safe.id]
    assert recovered[0].status == "QUEUED"
    assert recovered[0].attempts[0].status == "LEASE_EXPIRED"

    claimed_again = service.claim(claim_data("worker-safe-2"))
    assert claimed_again is not None and claimed_again.id == safe.id
    service.heartbeat(
        safe.id,
        ExecutionJobHeartbeatRequest(
            worker_id="worker-safe-2",
            lease_seconds=60,
            external_submission_possible=True,
            provider_call_count=1,
        ),
    )
    db_session.execute(
        update(ExecutionJob)
        .where(ExecutionJob.id == safe.id)
        .values(lease_expires_at=utc_now() - timedelta(seconds=1))
    )
    db_session.commit()
    unknown = service.recover_expired_leases()[0]
    assert unknown.status == "SUBMIT_UNKNOWN"
    assert unknown.uncertain is True
    assert unknown.attempts[-1].external_submission_possible is True
    with pytest.raises(AppError):
        service.retry(
            safe.id, ExecutionJobRetryRequest(retry_confirmed=True)
        )


def test_failed_retry_is_explicit_and_bounded(db_session: Session) -> None:
    service = ExecutionQueueService(db_session)
    job = service.create(create_data("retry", max_attempts=2)).job
    assert service.claim(claim_data("worker-1")) is not None
    failed = service.fail(
        job.id,
        ExecutionJobFailRequest(
            worker_id="worker-1",
            safe_error_code="SAFE_FAILURE",
            safe_error_details={"phase": "local"},
        ),
    )
    assert failed.status == "FAILED"
    assert service.retry(
        job.id, ExecutionJobRetryRequest(retry_confirmed=True)
    ).status == "QUEUED"
    assert service.claim(claim_data("worker-2")) is not None
    service.fail(
        job.id,
        ExecutionJobFailRequest(
            worker_id="worker-2", safe_error_code="SAFE_FAILURE"
        ),
    )
    with pytest.raises(AppError) as captured:
        service.retry(
            job.id, ExecutionJobRetryRequest(retry_confirmed=True)
        )
    assert getattr(captured.value, "status_code", None) == 409


def test_expired_final_safe_attempt_becomes_failed(db_session: Session) -> None:
    service = ExecutionQueueService(db_session)
    job = service.create(create_data("final-expiry", max_attempts=1)).job
    assert service.claim(claim_data("worker-final")) is not None
    db_session.execute(
        update(ExecutionJob)
        .where(ExecutionJob.id == job.id)
        .values(lease_expires_at=utc_now() - timedelta(seconds=1))
    )
    db_session.commit()
    recovered = service.recover_expired_leases()[0]
    assert recovered.status == "FAILED"
    assert recovered.safe_error_code == "LEASE_EXPIRED"
    with pytest.raises(AppError, match="maximum attempts"):
        service.retry(job.id, ExecutionJobRetryRequest(retry_confirmed=True))


def test_external_submission_cannot_fail_or_retry(db_session: Session) -> None:
    service = ExecutionQueueService(db_session)
    job = service.create(create_data("unknown", max_attempts=3)).job
    assert service.claim(claim_data("worker-external")) is not None
    service.heartbeat(
        job.id,
        ExecutionJobHeartbeatRequest(
            worker_id="worker-external",
            lease_seconds=60,
            external_submission_possible=True,
        ),
    )
    with pytest.raises(AppError):
        service.fail(
            job.id,
            ExecutionJobFailRequest(
                worker_id="worker-external", safe_error_code="MEDIA_UNCERTAIN"
            ),
        )
    unknown = service.mark_submit_unknown(
        job.id,
        ExecutionJobUnknownRequest(
            worker_id="worker-external",
            safe_error_code="MEDIA_UNCERTAIN",
            provider_call_count=1,
            provider_name="fake",
            provider_operation_id="safe-operation-id",
        ),
    )
    assert unknown.status == "SUBMIT_UNKNOWN"
    assert unknown.uncertain is True
    with pytest.raises(AppError):
        service.retry(job.id, ExecutionJobRetryRequest(retry_confirmed=True))


def test_state_recovers_in_a_new_file_database_session(tmp_path: Path) -> None:
    database = tmp_path / "queue-recovery.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as first:
        job = ExecutionQueueService(first).create(create_data("persisted")).job
    with sessions() as second:
        restored = ExecutionQueueService(second).get(job.id)
        assert restored.status == "QUEUED"
        assert restored.input_digest == digest("persisted")
    engine.dispose()


def test_two_workers_atomically_claim_one_job(tmp_path: Path) -> None:
    database = tmp_path / "queue-concurrency.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as setup:
        job_id = ExecutionQueueService(setup).create(
            create_data("concurrent-claim")
        ).job.id
    barrier = Barrier(2)

    def worker(worker_id: str) -> int | None:
        with sessions() as session:
            barrier.wait(timeout=5)
            claimed = ExecutionQueueService(session).claim(claim_data(worker_id))
            return None if claimed is None else claimed.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, ["worker-one", "worker-two"]))
    assert sorted(result for result in results if result is not None) == [job_id]
    assert results.count(None) == 1
    with sessions() as verify:
        assert verify.scalar(select(func.count(ExecutionAttempt.id))) == 1
        persisted = verify.get(ExecutionJob, job_id)
        assert persisted is not None and persisted.attempt_count == 1
    engine.dispose()


def test_running_concurrency_integrity_conflict_is_bounded_and_safe(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ExecutionQueueService(db_session)
    job = service.create(
        create_data("bounded-conflict", concurrency_key="shared")
    ).job
    calls = 0

    def conflicting_claim(**_: object) -> int | None:
        nonlocal calls
        calls += 1
        raise IntegrityError(
            "atomic claim",
            {},
            sqlite3.IntegrityError(
                "UNIQUE constraint failed: execution_jobs.concurrency_key"
            ),
        )

    monkeypatch.setattr(service.repository, "claim_next", conflicting_claim)
    assert service.claim(claim_data("worker-conflict")) is None
    assert calls == 3
    persisted = service.get(job.id)
    assert persisted.status == "QUEUED"
    assert persisted.attempt_count == 0
    assert persisted.attempts == []


def test_two_jobs_same_concurrency_key_allow_only_one_running(
    tmp_path: Path,
) -> None:
    database = tmp_path / "same-concurrency.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as setup:
        service = ExecutionQueueService(setup)
        first = service.create(
            create_data("same-key-a", concurrency_key="product:shared").model_copy(
                update={"job_type": "copy.variant.a"}
            )
        ).job
        second = service.create(
            create_data("same-key-b", concurrency_key="product:shared").model_copy(
                update={"job_type": "copy.variant.b"}
            )
        ).job
    barrier = Barrier(2)

    def worker(worker_id: str, job_type: str) -> int | None:
        with sessions() as session:
            barrier.wait(timeout=5)
            claimed = ExecutionQueueService(session).claim(
                ExecutionJobClaimRequest(
                    worker_id=worker_id,
                    lease_seconds=60,
                    job_types=[job_type],
                )
            )
            return None if claimed is None else claimed.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(worker, "worker-shared-a", "copy.variant.a"),
            executor.submit(worker, "worker-shared-b", "copy.variant.b"),
        ]
        results = [future.result(timeout=10) for future in futures]
    assert len([result for result in results if result is not None]) == 1
    with sessions() as verify:
        statuses = {
            job.id: job.status
            for job in verify.scalars(
                select(ExecutionJob).where(ExecutionJob.id.in_([first.id, second.id]))
            )
        }
        assert list(statuses.values()).count("RUNNING") == 1
        assert list(statuses.values()).count("QUEUED") == 1
        assert verify.scalar(select(func.count(ExecutionAttempt.id))) == 1
        assert sum(
            job.attempt_count
            for job in verify.scalars(
                select(ExecutionJob).where(ExecutionJob.id.in_([first.id, second.id]))
            )
        ) == 1
    engine.dispose()


def test_two_jobs_different_concurrency_keys_can_run_together(
    tmp_path: Path,
) -> None:
    database = tmp_path / "different-concurrency.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as setup:
        service = ExecutionQueueService(setup)
        expected = {
            service.create(
                create_data("key-a", concurrency_key="product:a").model_copy(
                    update={"job_type": "copy.key.a"}
                )
            ).job.id,
            service.create(
                create_data("key-b", concurrency_key="product:b").model_copy(
                    update={"job_type": "copy.key.b"}
                )
            ).job.id,
        }
    barrier = Barrier(2)

    def worker(worker_id: str, job_type: str) -> int | None:
        with sessions() as session:
            barrier.wait(timeout=5)
            claimed = ExecutionQueueService(session).claim(
                ExecutionJobClaimRequest(
                    worker_id=worker_id,
                    lease_seconds=60,
                    job_types=[job_type],
                )
            )
            return None if claimed is None else claimed.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(worker, "worker-key-a", "copy.key.a"),
            executor.submit(worker, "worker-key-b", "copy.key.b"),
        ]
        results = {future.result(timeout=10) for future in futures}
    assert results == expected
    with sessions() as verify:
        assert verify.scalar(
            select(func.count(ExecutionJob.id)).where(
                ExecutionJob.status == "RUNNING"
            )
        ) == 2
        assert verify.scalar(select(func.count(ExecutionAttempt.id))) == 2
    engine.dispose()


def test_concurrent_same_idempotency_input_reuses_one_job(tmp_path: Path) -> None:
    database = tmp_path / "queue-idempotency.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = Barrier(2)

    def worker() -> tuple[int, bool]:
        with sessions() as session:
            barrier.wait(timeout=5)
            result = ExecutionQueueService(session).create(
                create_data("concurrent-idempotency")
            )
            return result.job.id, result.reused

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: worker(), range(2)))
    assert {item[0] for item in results} == {1}
    assert sorted(item[1] for item in results) == [False, True]
    with sessions() as verify:
        assert verify.scalar(select(func.count(ExecutionJob.id))) == 1
    engine.dispose()


@pytest.mark.parametrize(
    "invalid_values",
    [
        {"status": "RUNNING"},
        {
            "lease_owner_digest": "A" * 64,
            "lease_expires_at": utc_now() + timedelta(seconds=60),
        },
        {"status": "SUBMIT_UNKNOWN", "uncertain": False},
        {"status": "QUEUED", "uncertain": True},
    ],
)
def test_database_rejects_invalid_lease_and_uncertain_state(
    db_session: Session, invalid_values: dict[str, object]
) -> None:
    job = ExecutionQueueService(db_session).create(
        create_data(f"invalid-constraint-{len(invalid_values)}-{sorted(invalid_values)}")
    ).job
    with pytest.raises(IntegrityError):
        db_session.execute(
            update(ExecutionJob)
            .where(ExecutionJob.id == job.id)
            .values(**invalid_values)
        )
        db_session.commit()
    db_session.rollback()


def test_running_concurrency_index_compiles_for_sqlite_and_postgresql() -> None:
    index = next(
        item
        for item in ExecutionJob.__table__.indexes
        if item.name == "uq_execution_jobs_running_concurrency_key"
    )
    sqlite_sql = str(CreateIndex(index).compile(dialect=sqlite.dialect()))
    postgres_sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE INDEX" in sqlite_sql
    assert "WHERE concurrency_key IS NOT NULL AND status = 'RUNNING'" in sqlite_sql
    assert "UNIQUE INDEX" in postgres_sql
    assert (
        "WHERE concurrency_key IS NOT NULL AND status = 'RUNNING'" in postgres_sql
    )


def test_execution_job_api_never_exposes_lease_owner_digest(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/execution-jobs",
        json=create_data("api-lease-safety").model_dump(mode="json"),
    ).json()["job"]
    worker_id = "worker-api-safety"
    claimed = client.post(
        "/api/v1/execution-jobs/claim",
        json=claim_data(worker_id).model_dump(),
    ).json()["job"]
    restored = client.get(f"/api/v1/execution-jobs/{created['id']}").json()
    for body in (claimed, restored):
        assert body["lease_active"] is True
        assert "lease_owner_digest" not in body
        assert "lease_expires_at" not in body
        assert worker_id not in json.dumps(body)
        assert digest(worker_id) not in json.dumps(body)


def test_0003_upgrade_to_queue_head_preserves_existing_data(tmp_path: Path) -> None:
    database = tmp_path / "brand-runtime.db"
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", migration_service.BRAND_KIT_REVISION
    )
    now = utc_now().isoformat()
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO brand_kits (id,name,created_at,updated_at) VALUES (1,?,?,?)",
            ("Migration Brand", now, now),
        )
        connection.execute(
            """INSERT INTO brand_kit_versions
            (id,brand_kit_id,version_number,digest,brand_name,positioning,
             default_language,brand_tone,preferred_terms,forbidden_terms,
             target_regions,audience_guidelines,visual_guidelines,
             required_disclosures,claims_constraints,created_at)
            VALUES (1,1,1,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "D" * 64,
                "Migration Brand",
                "Stable positioning",
                "English",
                "Clear",
                "[]",
                "[]",
                "[]",
                "[]",
                "[]",
                "[]",
                "[]",
                now,
            ),
        )
        connection.execute(
            """INSERT INTO products
            (id,name,category,description,selling_points,target_markets,
             created_at,updated_at,brand_kit_version_id)
            VALUES (1,'Stable Product',NULL,'Stable','[""Point""]','[]',?,?,1)""",
            (now, now),
        )
        connection.commit()
        before = connection.execute(
            "SELECT id,name,brand_kit_version_id FROM products"
        ).fetchall()
    finally:
        connection.close()

    result = migration_service.upgrade_sqlite_database(
        database, tmp_path / "backups"
    )
    assert result.previous_revision == migration_service.BRAND_KIT_REVISION
    assert result.current_revision == migration_service.HEAD_REVISION
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT id,name,brand_kit_version_id FROM products"
        ).fetchall() == before
        assert connection.execute("SELECT count(*) FROM execution_jobs").fetchone()[
            0
        ] == 0
        assert connection.execute(
            "SELECT count(*) FROM execution_attempts"
        ).fetchone()[0] == 0
        index_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
            ("uq_execution_jobs_running_concurrency_key",),
        ).fetchone()[0]
        assert "WHERE concurrency_key IS NOT NULL AND status = 'RUNNING'" in index_sql
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='execution_jobs'"
        ).fetchone()[0]
        assert "ck_execution_jobs_lease_state" in table_sql
        assert "ck_execution_jobs_uncertain_status" in table_sql
    finally:
        connection.close()


def test_read_only_status_recognizes_0003_as_upgradeable(tmp_path: Path) -> None:
    database = tmp_path / "brand-status.db"
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", migration_service.BRAND_KIT_REVISION
    )
    before = migration_service.sha256_file(database)
    status = migration_service.get_database_migration_status(database)
    assert status.state == "brand_kit_runtime"
    assert status.revision == migration_service.BRAND_KIT_REVISION
    assert status.upgrade_required is True
    assert migration_service.sha256_file(database) == before


def test_queue_routes_resolve_no_provider_dependencies(
    client: TestClient,
) -> None:
    calls = 0

    def forbidden(*_: object, **__: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("Provider dependency must not be resolved")

    app.dependency_overrides[get_text_generation_provider] = forbidden
    app.dependency_overrides[get_visual_generation_provider] = forbidden
    app.dependency_overrides[get_youtube_provider] = forbidden
    response = client.post(
        "/api/v1/execution-jobs",
        json=create_data("provider-free").model_dump(mode="json"),
    )
    assert response.status_code == 201
    assert client.get("/api/v1/execution-jobs").status_code == 200
    assert calls == 0
