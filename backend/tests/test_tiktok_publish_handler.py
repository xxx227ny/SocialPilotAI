from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import (
    ExecutionJob,
    Product,
    PublishTask,
    VideoRenderArtifact,
)
from app.models.social import TikTokCreatorInfoSnapshot
from app.providers.tiktok_provider import TikTokProviderError
from tests.test_tiktok_publish_queue_e2e import (
    FakeProvider,
    creator_snapshot,
    metadata,
    run_worker,
    setup_runtime,
)


class _CommitFaults:
    def __init__(self, status: str, *, failures: int = 1) -> None:
        self.status = status
        self.failures = failures
        self.rollback_count = 0
        self.recovered_task_ids: list[int] = []
        self._must_rollback: set[int] = set()

    def session_factory(self, bind: Any) -> Callable[[], Session]:
        sessions = sessionmaker(bind=bind, expire_on_commit=False)

        def create() -> Session:
            session = sessions()
            original_commit = session.commit
            original_rollback = session.rollback
            original_get = session.get

            def commit() -> None:
                identity = id(session)
                if identity in self._must_rollback:
                    raise RuntimeError("fake transaction requires rollback")
                matching = [
                    value
                    for value in session.dirty
                    if isinstance(value, PublishTask) and value.status == self.status
                ]
                if matching and self.failures:
                    self.failures -= 1
                    self._must_rollback.add(identity)
                    raise RuntimeError("fake task commit failure")
                original_commit()

            def rollback() -> None:
                self.rollback_count += 1
                self._must_rollback.discard(id(session))
                original_rollback()

            def get(entity: Any, ident: Any, **kwargs: Any):
                if entity is PublishTask and self.rollback_count:
                    self.recovered_task_ids.append(int(ident))
                return original_get(entity, ident, **kwargs)

            session.commit = commit  # type: ignore[method-assign]
            session.rollback = rollback  # type: ignore[method-assign]
            session.get = get  # type: ignore[method-assign]
            return session

        return create


def _run_worker_with_factory(
    session_factory: Callable[[], Session],
    settings: Any,
    storage: Any,
    probe: Any,
    provider: FakeProvider,
    worker_id: str,
):
    registry = build_execution_handler_registry(
        session_factory=session_factory,
        settings=settings,
        tiktok_provider_factory=lambda _: provider,
        tiktok_media_probe=probe,
        artifact_storage=storage,
    )
    return ExecutionWorker(
        session_factory=session_factory,
        registry=registry,
        worker_id=worker_id,
        heartbeat_interval_seconds=0.05,
    ).run_once()


def _task_for_job(db_session: Session, job_id: int) -> PublishTask:
    job = db_session.get(ExecutionJob, job_id)
    return db_session.get(PublishTask, job.input_payload["publish_task_id"])


def test_init_exception_is_submit_unknown_and_restart_has_zero_calls(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime = setup_runtime(db_session, tmp_path)
    settings, storage, probe, product_id, artifact_id, account = runtime
    provider = FakeProvider()
    snapshot = creator_snapshot(client, db_session, runtime, provider)
    data = metadata(account, artifact_id, snapshot)
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok/preflight", json=data
    ).json()
    queued = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok",
        json=data
        | {
            "input_digest": checked["input_digest"],
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
            "confirm_upload": True,
        },
    )

    async def fail_init(**_: object):
        provider.calls["init"] += 1
        raise RuntimeError("fake init uncertainty")

    provider.initialize_direct_post = fail_init
    assert (
        run_worker(
            db_session, settings, storage, probe, provider, "unknown-worker"
        ).status
        == WorkerRunStatus.SUBMIT_UNKNOWN
    )
    job = db_session.get(ExecutionJob, queued.json()["job"]["id"])
    task = db_session.get(PublishTask, job.input_payload["publish_task_id"])
    assert job.status == task.status == "SUBMIT_UNKNOWN"
    assert task.uncertain is True and provider.calls["init"] == 1
    assert (
        run_worker(
            db_session, settings, storage, probe, provider, "restart-worker"
        ).status
        == WorkerRunStatus.NO_JOB
    )
    assert provider.calls["init"] == 1 and provider.calls["chunk"] == 0


def test_local_frozen_input_change_fails_before_provider(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime = setup_runtime(db_session, tmp_path)
    settings, storage, probe, product_id, artifact_id, account = runtime
    provider = FakeProvider()
    snapshot = creator_snapshot(client, db_session, runtime, provider)
    data = metadata(account, artifact_id, snapshot)
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok/preflight", json=data
    ).json()
    queued = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok",
        json=data
        | {
            "input_digest": checked["input_digest"],
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
            "confirm_upload": True,
        },
    )
    job = db_session.get(ExecutionJob, queued.json()["job"]["id"])
    task = db_session.get(PublishTask, job.input_payload["publish_task_id"])
    task.title = "Changed after enqueue"
    db_session.commit()
    result = run_worker(db_session, settings, storage, probe, provider, "failed-worker")
    assert result.status == WorkerRunStatus.FAILED
    db_session.refresh(task)
    assert task.status == "FAILED"
    assert provider.calls["init"] == provider.calls["chunk"] == 0


def _submitted(client, db_session, tmp_path):
    runtime = setup_runtime(db_session, tmp_path)
    _, _, _, product_id, artifact_id, account = runtime
    provider = FakeProvider()
    snapshot = creator_snapshot(client, db_session, runtime, provider)
    data = metadata(account, artifact_id, snapshot)
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok/preflight", json=data
    ).json()
    response = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok",
        json=data
        | {
            "input_digest": checked["input_digest"],
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
            "confirm_upload": True,
        },
    )
    return runtime, provider, response.json()["job"]["id"], account


def test_token_decryption_failure_is_failed_before_init(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime, provider, job_id, account = _submitted(client, db_session, tmp_path)
    settings, storage, probe, *_ = runtime
    account.access_token_ciphertext = "invalid-ciphertext"
    db_session.commit()
    result = run_worker(
        db_session, settings, storage, probe, provider, "decrypt-worker"
    )
    task = db_session.get(
        PublishTask,
        db_session.get(ExecutionJob, job_id).input_payload["publish_task_id"],
    )
    assert result.status == WorkerRunStatus.FAILED and task.status == "FAILED"
    assert (
        provider.calls["refresh"]
        == provider.calls["init"]
        == provider.calls["chunk"]
        == 0
    )


def test_token_refresh_failure_is_failed_before_init(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime, provider, job_id, account = _submitted(client, db_session, tmp_path)
    settings, storage, probe, *_ = runtime
    account.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    async def fail_refresh(_: str):
        provider.calls["refresh"] += 1
        raise TikTokProviderError("fake_refresh_rejected")

    provider.refresh_access_token = fail_refresh
    result = run_worker(
        db_session, settings, storage, probe, provider, "refresh-fail-worker"
    )
    task = db_session.get(
        PublishTask,
        db_session.get(ExecutionJob, job_id).input_payload["publish_task_id"],
    )
    assert result.status == WorkerRunStatus.FAILED and task.status == "FAILED"
    assert provider.calls["refresh"] == 1
    assert provider.calls["init"] == provider.calls["chunk"] == 0


def test_chunk_exception_is_unknown_and_restart_has_zero_delta(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime, provider, job_id, _ = _submitted(client, db_session, tmp_path)
    settings, storage, probe, *_ = runtime

    async def fail_chunk(**_: object):
        provider.calls["chunk"] += 1
        raise RuntimeError("fake chunk uncertainty")

    provider.upload_video_chunk = fail_chunk
    result = run_worker(db_session, settings, storage, probe, provider, "chunk-worker")
    task = db_session.get(
        PublishTask,
        db_session.get(ExecutionJob, job_id).input_payload["publish_task_id"],
    )
    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert task.status == "SUBMIT_UNKNOWN" and task.uncertain is True
    assert provider.calls["init"] == provider.calls["chunk"] == 1
    assert (
        run_worker(
            db_session, settings, storage, probe, provider, "restart-worker"
        ).status
        == WorkerRunStatus.NO_JOB
    )
    assert provider.calls["init"] == provider.calls["chunk"] == 1


def test_init_identity_commit_failure_is_unknown_and_restart_does_not_submit(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime, provider, job_id, _ = _submitted(client, db_session, tmp_path)
    settings, storage, probe, *_ = runtime
    faults = _CommitFaults("UPLOADING")
    sessions = faults.session_factory(db_session.bind)

    result = _run_worker_with_factory(
        sessions, settings, storage, probe, provider, "identity-save-worker"
    )
    db_session.expire_all()
    task = _task_for_job(db_session, job_id)
    job = db_session.get(ExecutionJob, job_id)
    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert job.status == task.status == "SUBMIT_UNKNOWN"
    assert task.uncertain is True
    assert provider.calls["init"] == 1 and provider.calls["chunk"] == 0
    assert faults.rollback_count == 1
    assert faults.recovered_task_ids == [task.id]
    assert "fake-publish-id" not in str(job.safe_error_details)
    assert "upload.tiktokapis.com" not in str(job.safe_error_details)
    assert (
        _run_worker_with_factory(
            sessions, settings, storage, probe, provider, "identity-restart-worker"
        ).status
        == WorkerRunStatus.NO_JOB
    )
    assert provider.calls["init"] == 1 and provider.calls["chunk"] == 0


def test_processing_commit_failure_is_unknown_without_upload_replay(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime, provider, job_id, _ = _submitted(client, db_session, tmp_path)
    settings, storage, probe, *_ = runtime
    faults = _CommitFaults("PROCESSING")
    sessions = faults.session_factory(db_session.bind)

    result = _run_worker_with_factory(
        sessions, settings, storage, probe, provider, "processing-save-worker"
    )
    db_session.expire_all()
    task = _task_for_job(db_session, job_id)
    job = db_session.get(ExecutionJob, job_id)
    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert job.status == task.status == "SUBMIT_UNKNOWN"
    assert task.uncertain is True and task.status != "SUCCEEDED"
    assert provider.calls["init"] == provider.calls["chunk"] == 1
    assert (
        _run_worker_with_factory(
            sessions, settings, storage, probe, provider, "processing-restart-worker"
        ).status
        == WorkerRunStatus.NO_JOB
    )
    assert provider.calls["init"] == provider.calls["chunk"] == 1


def test_unknown_first_commit_failure_recovers_exact_task_id(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime, provider, job_id, _ = _submitted(client, db_session, tmp_path)
    settings, storage, probe, *_ = runtime

    async def fail_init(**_: object):
        provider.calls["init"] += 1
        raise RuntimeError("provider body must not escape")

    provider.initialize_direct_post = fail_init
    faults = _CommitFaults("SUBMIT_UNKNOWN")
    result = _run_worker_with_factory(
        faults.session_factory(db_session.bind),
        settings,
        storage,
        probe,
        provider,
        "unknown-recovery-worker",
    )
    db_session.expire_all()
    task = _task_for_job(db_session, job_id)
    job = db_session.get(ExecutionJob, job_id)
    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert faults.rollback_count == 1
    assert faults.recovered_task_ids == [task.id]
    assert task.status == "SUBMIT_UNKNOWN" and task.uncertain is True
    assert task.safe_error_code == "tiktok_submit_result_uncertain"
    assert job.status == "SUBMIT_UNKNOWN"
    assert db_session.scalar(select(func.count(PublishTask.id))) == 1
    assert "provider body" not in str(task.safe_error_code)
    assert "provider body" not in str(job.safe_error_details)


@pytest.mark.parametrize(
    "changed_source",
    ["product", "account", "creator_snapshot", "artifact", "source_chain"],
)
def test_frozen_source_change_fails_task_before_provider(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    changed_source: str,
) -> None:
    runtime, provider, job_id, account = _submitted(client, db_session, tmp_path)
    settings, storage, probe, product_id, artifact_id, _ = runtime
    task = _task_for_job(db_session, job_id)
    job = db_session.get(ExecutionJob, job_id)
    snapshot = db_session.get(
        TikTokCreatorInfoSnapshot, job.input_payload["creator_info_snapshot_id"]
    )
    artifact = db_session.get(VideoRenderArtifact, artifact_id)
    if changed_source == "product":
        other = Product(
            name="Other Product",
            description="A legal alternate Product",
            selling_points=["separate"],
            target_markets=[],
        )
        db_session.add(other)
        db_session.flush()
        task.product_id = other.id
    elif changed_source == "account":
        account.provider_account_id = "changed-open-id"
    elif changed_source == "creator_snapshot":
        snapshot.request_digest = "b" * 64
    elif changed_source == "artifact":
        artifact.artifact_metadata = artifact.artifact_metadata | {"sha256": "0" * 64}
    else:
        artifact.video_render_task.status = "FAILED"
    db_session.commit()
    task_count = db_session.scalar(select(func.count(PublishTask.id)))
    job_count = db_session.scalar(select(func.count(ExecutionJob.id)))

    result = run_worker(
        db_session, settings, storage, probe, provider, f"frozen-{changed_source}"
    )
    db_session.expire_all()
    task = _task_for_job(db_session, job_id)
    job = db_session.get(ExecutionJob, job_id)
    assert result.status == WorkerRunStatus.FAILED
    assert task.status == job.status == "FAILED"
    assert task.uncertain is False and job.uncertain is False
    assert provider.calls["init"] == provider.calls["chunk"] == 0
    assert db_session.scalar(select(func.count(PublishTask.id))) == task_count
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == job_count
