from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    get_settings,
    get_tiktok_media_probe,
    get_video_artifact_storage,
)
from app.core.config import Settings
from app.db.base import Base
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.main import app
from app.models import ExecutionJob, PublishTask, SocialAccount
from app.models.social import TikTokCreatorInfoSnapshot
from app.providers.tiktok_provider import (
    TikTokCreatorInfo,
    TikTokDirectPostSession,
    TikTokPublishStatus,
)
from app.schemas.social import TikTokPublishingMetadata, TikTokPublishRequest
from app.services.social_security import TokenCipher
from app.services.tiktok_media_probe import TikTokMediaSpecification
from app.services.tiktok_publish_job_service import TikTokPublishJobService
from app.services.tiktok_publish_preflight import TikTokPublishPreflightService
from app.services.tiktok_publish_service import TikTokPublishService
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from tests.test_social_publishing import create_publishable_artifact


class FakeProbe:
    def probe(self, path: Path) -> TikTokMediaSpecification:
        assert path.is_absolute() and path.is_file()
        return TikTokMediaSpecification(
            "mov,mp4", "h264", 30, 15, 1080, 1920, "aac", 48_000, 8_000_000
        )


class FakeProvider:
    def __init__(self) -> None:
        self.calls = {"refresh": 0, "creator": 0, "init": 0, "chunk": 0, "status": 0}
        self.status = "PROCESSING_UPLOAD"

    async def refresh_access_token(self, refresh_token: str):
        self.calls["refresh"] += 1
        raise AssertionError("refresh was not expected")

    async def query_creator_info(self, **_: object) -> TikTokCreatorInfo:
        self.calls["creator"] += 1
        return TikTokCreatorInfo(
            "safe_creator",
            "Safe Creator",
            ("SELF_ONLY", "PUBLIC_TO_EVERYONE"),
            False,
            False,
            False,
            60,
        )

    async def initialize_direct_post(self, **_: object) -> TikTokDirectPostSession:
        self.calls["init"] += 1
        return TikTokDirectPostSession(
            "fake-publish-id", "https://upload.tiktokapis.com/fake-session"
        )

    async def upload_video_chunk(self, **_: object) -> None:
        self.calls["chunk"] += 1

    async def fetch_publish_status(self, **_: object) -> TikTokPublishStatus:
        self.calls["status"] += 1
        return TikTokPublishStatus(self.status)


def setup_runtime(db: Session, tmp_path: Path):
    settings = Settings(
        _env_file=None,
        enable_tiktok_publishing=True,
        tiktok_client_key="fake-key",
        tiktok_client_secret="fake-secret",
        tiktok_oauth_redirect_uri="https://app.example/tiktok/callback",
        social_token_encryption_key=Fernet.generate_key().decode(),
        video_artifact_storage_root=str(tmp_path.resolve()),
    )
    storage = LocalVideoArtifactStorage(tmp_path.resolve(), 100_000_000)
    product_id, artifact_id = create_publishable_artifact(db, storage)
    account = SocialAccount(
        product_id=product_id,
        platform="tiktok",
        provider_account_id="fake-open-id",
        display_name="Safe Creator",
        scopes=["user.info.basic", "video.publish"],
        access_token_ciphertext=TokenCipher(settings).encrypt("fake-access-token"),
        refresh_token_ciphertext=TokenCipher(settings).encrypt("fake-refresh-token"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        refresh_token_expires_at=datetime.now(UTC) + timedelta(days=30),
        connection_status="CONNECTED",
        encryption_key_id="test-key",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    probe = FakeProbe()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_video_artifact_storage] = lambda: storage
    app.dependency_overrides[get_tiktok_media_probe] = lambda: probe
    return settings, storage, probe, product_id, artifact_id, account


def run_worker(db: Session, settings, storage, probe, provider, worker_id: str):
    sessions = sessionmaker(bind=db.bind, expire_on_commit=False)
    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=settings,
        tiktok_provider_factory=lambda _: provider,
        tiktok_media_probe=probe,
        artifact_storage=storage,
    )
    return ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id=worker_id,
        heartbeat_interval_seconds=0.05,
    ).run_once()


def creator_snapshot(client: TestClient, db: Session, runtime, provider):
    settings, storage, probe, product_id, _, account = runtime
    response = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok/creator-info",
        json={"social_account_id": account.id, "request_id": "creator-request-0001"},
    )
    assert response.status_code == 201 and sum(provider.calls.values()) == 0
    assert (
        run_worker(db, settings, storage, probe, provider, "creator-worker").status
        == WorkerRunStatus.SUCCEEDED
    )
    job = db.get(ExecutionJob, response.json()["job"]["id"])
    assert provider.calls["creator"] == 1
    assert job.result_entity_type == "tiktok_creator_info_snapshot"
    return db.get(TikTokCreatorInfoSnapshot, job.result_entity_id)


def metadata(account, artifact_id, snapshot):
    return {
        "social_account_id": account.id,
        "creator_info_snapshot_id": snapshot.id,
        "artifact_id": artifact_id,
        "title": "Safe local TikTok task",
        "description": "Safe caption",
        "tags": ["AI", "Demo"],
        "privacy_status": "SELF_ONLY",
        "disable_comment": False,
        "disable_duet": False,
        "disable_stitch": False,
        "brand_content_toggle": False,
        "brand_organic_toggle": True,
    }


def test_three_job_flow_provider_counts_and_terminal_refresh_replay(
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
    submit = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok",
        json=data
        | {
            "input_digest": checked["input_digest"],
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
            "confirm_upload": True,
        },
    )
    assert submit.status_code == 201 and provider.calls["init"] == 0
    assert (
        run_worker(
            db_session, settings, storage, probe, provider, "submit-worker"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    job = db_session.get(ExecutionJob, submit.json()["job"]["id"])
    task = db_session.get(PublishTask, job.result_entity_id)
    assert task.status == "PROCESSING"
    assert provider.calls == {
        "refresh": 0,
        "creator": 1,
        "init": 1,
        "chunk": 1,
        "status": 0,
    }
    refresh_request = {
        "product_id": product_id,
        "refresh_request_id": "refresh-request-0001",
    }
    refresh = client.post(
        f"/api/v1/publish-tasks/{task.id}/tiktok/refresh", json=refresh_request
    )
    provider.status = "PUBLISH_COMPLETE"
    assert (
        run_worker(
            db_session, settings, storage, probe, provider, "refresh-worker"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    db_session.refresh(task)
    assert task.status == "SUCCEEDED" and provider.calls["status"] == 1
    replay = client.post(
        f"/api/v1/publish-tasks/{task.id}/tiktok/refresh", json=refresh_request
    )
    assert replay.status_code == 201 and replay.json()["reused"] is True
    assert replay.json()["job"]["id"] == refresh.json()["job"]["id"]
    assert provider.calls["status"] == 1
    assert (
        run_worker(
            db_session, settings, storage, probe, provider, "restart-worker"
        ).status
        == WorkerRunStatus.NO_JOB
    )
    assert provider.calls == {
        "refresh": 0,
        "creator": 1,
        "init": 1,
        "chunk": 1,
        "status": 1,
    }
    new_refresh = client.post(
        f"/api/v1/publish-tasks/{task.id}/tiktok/refresh",
        json={"product_id": product_id, "refresh_request_id": "refresh-request-0002"},
    )
    assert new_refresh.status_code == 409


def test_snapshot_read_is_product_and_account_isolated(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime = setup_runtime(db_session, tmp_path)
    _, _, _, product_id, _, account = runtime
    snapshot = creator_snapshot(client, db_session, runtime, FakeProvider())
    path = f"/api/v1/tiktok-creator-info-snapshots/{snapshot.id}"
    assert (
        client.get(
            path, params={"product_id": product_id, "social_account_id": account.id}
        ).status_code
        == 200
    )
    assert (
        client.get(
            path, params={"product_id": product_id + 1, "social_account_id": account.id}
        ).status_code
        == 404
    )
    assert (
        client.get(
            path, params={"product_id": product_id, "social_account_id": account.id + 1}
        ).status_code
        == 404
    )


def _queued_submit(client, db_session, tmp_path):
    runtime = setup_runtime(db_session, tmp_path)
    _, _, _, product_id, artifact_id, account = runtime
    provider = FakeProvider()
    snapshot = creator_snapshot(client, db_session, runtime, provider)
    data = metadata(account, artifact_id, snapshot)
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok/preflight", json=data
    ).json()
    request = data | {
        "input_digest": checked["input_digest"],
        "preflight_digest": checked["preflight_digest"],
        "preflight_expires_at": checked["expires_at"],
        "confirm_upload": True,
    }
    response = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok", json=request
    )
    assert response.status_code == 201
    return runtime, provider, request, response.json()["job"]["id"]


@pytest.mark.parametrize(
    ("payload_field", "replacement"),
    [
        ("preflight_digest", "0" * 64),
        ("preflight_expires_at", "2099-01-01T00:00:00Z"),
        ("frozen_input_digest", "1" * 64),
    ],
)
def test_submit_replay_rejects_saved_preflight_identity_tampering(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    payload_field: str,
    replacement: str,
) -> None:
    runtime, provider, request, job_id = _queued_submit(client, db_session, tmp_path)
    product_id = runtime[3]
    job = db_session.get(ExecutionJob, job_id)
    payload = dict(job.input_payload)
    payload[payload_field] = replacement
    job.input_payload = payload
    db_session.commit()
    before_tasks = db_session.scalar(select(func.count(PublishTask.id)))
    before_jobs = db_session.scalar(select(func.count(ExecutionJob.id)))
    replay = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok", json=request
    )
    assert replay.status_code == 409
    assert db_session.scalar(select(func.count(PublishTask.id))) == before_tasks
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == before_jobs
    assert provider.calls["init"] == provider.calls["chunk"] == 0


def test_submit_job_failure_rolls_back_task_atomically(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime = setup_runtime(db_session, tmp_path)
    _, _, _, product_id, artifact_id, account = runtime
    provider = FakeProvider()
    snapshot = creator_snapshot(client, db_session, runtime, provider)
    data = metadata(account, artifact_id, snapshot)
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/tiktok/preflight", json=data
    ).json()

    def reject_job(session, _flush_context, _instances):
        if any(isinstance(value, ExecutionJob) for value in session.new):
            raise RuntimeError("fake queue persistence failure")

    event.listen(db_session, "before_flush", reject_job)
    try:
        with pytest.raises(RuntimeError, match="fake queue persistence failure"):
            client.post(
                f"/api/v1/products/{product_id}/publishing/tiktok",
                json=data
                | {
                    "input_digest": checked["input_digest"],
                    "preflight_digest": checked["preflight_digest"],
                    "preflight_expires_at": checked["expires_at"],
                    "confirm_upload": True,
                },
            )
    finally:
        event.remove(db_session, "before_flush", reject_job)
    assert db_session.scalar(select(func.count(PublishTask.id))) == 0
    assert (
        db_session.scalar(
            select(func.count(ExecutionJob.id)).where(
                ExecutionJob.job_type == "tiktok.publish.submit.v1"
            )
        )
        == 0
    )
    assert provider.calls["init"] == provider.calls["chunk"] == 0


def test_refresh_replay_rejects_job_and_payload_digest_tampering(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    runtime, provider, _, submit_job_id = _queued_submit(client, db_session, tmp_path)
    settings, storage, probe, product_id, _, _ = runtime
    assert (
        run_worker(
            db_session, settings, storage, probe, provider, "submit-worker"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    submit_job = db_session.get(ExecutionJob, submit_job_id)
    task = db_session.get(PublishTask, submit_job.result_entity_id)
    request = {"product_id": product_id, "refresh_request_id": "refresh-tamper-0001"}
    response = client.post(
        f"/api/v1/publish-tasks/{task.id}/tiktok/refresh", json=request
    )
    assert response.status_code == 201
    refresh_job = db_session.get(ExecutionJob, response.json()["job"]["id"])
    payload = dict(refresh_job.input_payload)
    payload["frozen_task_digest"] = "2" * 64
    refresh_job.input_payload = payload
    refresh_job.input_digest = "2" * 64
    db_session.commit()
    replay = client.post(
        f"/api/v1/publish-tasks/{task.id}/tiktok/refresh", json=request
    )
    assert replay.status_code == 409
    assert provider.calls["status"] == 0


def test_two_sessions_same_submit_converge_to_one_task_and_job(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    seed = sessions()
    runtime = setup_runtime(seed, tmp_path)
    _, _, _, product_id, artifact_id, account = runtime
    provider = FakeProvider()
    info = TikTokCreatorInfo(
        "safe_creator", "Safe Creator", ("SELF_ONLY",), False, False, False, 60
    )
    snapshot = TikTokPublishService(seed, runtime[0]).create_snapshot(
        product_id=product_id, account=account, info=info, request_digest="a" * 64
    )
    data = metadata(account, artifact_id, snapshot)
    typed_data = TikTokPublishingMetadata.model_validate(data)
    checked = TikTokPublishPreflightService(
        seed, runtime[0], runtime[1], runtime[2]
    ).run(product_id, typed_data)
    request = TikTokPublishRequest.model_validate(
        data
        | {
            "input_digest": checked.input_digest,
            "preflight_digest": checked.preflight_digest,
            "preflight_expires_at": checked.expires_at,
            "confirm_upload": True,
        }
    )
    barrier = __import__("threading").Barrier(2)

    def submit_once():
        session = sessions()
        try:
            barrier.wait()
            return TikTokPublishJobService(
                session, runtime[0], runtime[1], runtime[2]
            ).enqueue_submit(product_id, request)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: submit_once(), range(2)))
    assert len({response.job.id for response in responses}) == 1
    assert seed.scalar(select(func.count(PublishTask.id))) == 1
    assert (
        seed.scalar(
            select(func.count(ExecutionJob.id)).where(
                ExecutionJob.job_type == "tiktok.publish.submit.v1"
            )
        )
        == 1
    )
    assert provider.calls["init"] == provider.calls["chunk"] == 0
    seed.close()
    engine.dispose()


def test_two_workers_compete_for_one_submit_job_and_upload_once(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker-competition.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    seed = sessions()
    runtime = setup_runtime(seed, tmp_path)
    settings, storage, probe, product_id, artifact_id, account = runtime
    provider = FakeProvider()
    info = TikTokCreatorInfo(
        "safe_creator", "Safe Creator", ("SELF_ONLY",), False, False, False, 60
    )
    snapshot = TikTokPublishService(seed, settings).create_snapshot(
        product_id=product_id, account=account, info=info, request_digest="c" * 64
    )
    data = metadata(account, artifact_id, snapshot)
    typed_data = TikTokPublishingMetadata.model_validate(data)
    checked = TikTokPublishPreflightService(seed, settings, storage, probe).run(
        product_id, typed_data
    )
    request = TikTokPublishRequest.model_validate(
        data
        | {
            "input_digest": checked.input_digest,
            "preflight_digest": checked.preflight_digest,
            "preflight_expires_at": checked.expires_at,
            "confirm_upload": True,
        }
    )
    queued = TikTokPublishJobService(seed, settings, storage, probe).enqueue_submit(
        product_id, request
    )
    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=settings,
        tiktok_provider_factory=lambda _: provider,
        tiktok_media_probe=probe,
        artifact_storage=storage,
    )
    workers = [
        ExecutionWorker(
            session_factory=sessions,
            registry=registry,
            worker_id=f"competing-worker-{index}",
            heartbeat_interval_seconds=0.05,
        )
        for index in range(2)
    ]
    barrier = __import__("threading").Barrier(2)

    def run(worker: ExecutionWorker):
        barrier.wait()
        return worker.run_once()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, workers))
    seed.expire_all()
    job = seed.get(ExecutionJob, queued.job.id)
    task = seed.get(PublishTask, job.result_entity_id)
    assert {result.status for result in results} == {
        WorkerRunStatus.SUCCEEDED,
        WorkerRunStatus.NO_JOB,
    }
    assert provider.calls["init"] == provider.calls["chunk"] == 1
    assert seed.scalar(select(func.count(PublishTask.id))) == 1
    assert (
        seed.scalar(
            select(func.count(ExecutionJob.id)).where(
                ExecutionJob.job_type == "tiktok.publish.submit.v1"
            )
        )
        == 1
    )
    assert job.status == "SUCCEEDED"
    assert job.result_entity_type == "publish_task"
    assert job.result_entity_id == task.id
    seed.close()
    engine.dispose()


@pytest.mark.parametrize(
    "job_type",
    [
        "tiktok.publish.creator_info.v1",
        "tiktok.publish.submit.v1",
        "tiktok.publish.refresh.v1",
    ],
)
def test_generic_execution_endpoint_rejects_tiktok_provider_jobs(
    client: TestClient, job_type: str
) -> None:
    response = client.post(
        "/api/v1/execution-jobs",
        json={
            "job_type": job_type,
            "source_type": "product",
            "source_id": 1,
            "input_digest": "a" * 64,
            "idempotency_key": f"blocked-{job_type}",
            "input_payload": {},
            "estimated_cost": "0",
            "currency": "USD",
            "cost_confirmed": True,
            "max_attempts": 1,
        },
    )
    assert response.status_code == 409
