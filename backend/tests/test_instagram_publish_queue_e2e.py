from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    get_instagram_media_probe,
    get_settings,
    get_video_artifact_storage,
)
from app.core.config import Settings
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.main import app
from app.models import ExecutionJob, PublishTask, SocialAccount
from app.providers.instagram_provider import (
    InstagramContainerStatus,
    InstagramPublishedReel,
    InstagramReelContainer,
)
from app.services.instagram_media_probe import InstagramMediaSpecification
from app.services.social_security import TokenCipher
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from tests.test_social_publishing import create_publishable_artifact


class FakeProbe:
    def probe(self, path: Path) -> InstagramMediaSpecification:
        assert path.is_absolute() and path.is_file()
        return InstagramMediaSpecification(
            "mov,mp4", "h264", 30, 15, 1080, 1920, "aac", 48_000
        )


class FakeProvider:
    def __init__(self) -> None:
        self.calls = {"create": 0, "upload": 0, "status": 0, "publish": 0}

    async def create_resumable_reel_container(self, **kwargs: object):
        self.calls["create"] += 1
        return InstagramReelContainer(
            "fake-container", "https://rupload.facebook.com/ig-api-upload/fake"
        )

    async def upload_reel_bytes(self, **kwargs: object) -> None:
        self.calls["upload"] += 1

    async def get_container_status(self, **kwargs: object):
        self.calls["status"] += 1
        return InstagramContainerStatus("FINISHED")

    async def publish_reel(self, **kwargs: object):
        self.calls["publish"] += 1
        return InstagramPublishedReel("fake-final-media")


def setup_runtime(db: Session, tmp_path: Path):
    settings = Settings(
        _env_file=None,
        enable_instagram_publishing=True,
        instagram_app_id="fake-app",
        instagram_app_secret="fake-secret",
        instagram_oauth_redirect_uri="http://127.0.0.1/callback",
        social_token_encryption_key=Fernet.generate_key().decode(),
        video_artifact_storage_root=str(tmp_path.resolve()),
    )
    storage = LocalVideoArtifactStorage(tmp_path.resolve(), 1_000_000)
    probe = FakeProbe()
    product_id, artifact_id = create_publishable_artifact(db, storage)
    account = SocialAccount(
        product_id=product_id,
        platform="instagram",
        provider_account_id="178414000000001",
        display_name="fake_professional",
        scopes=["instagram_business_basic", "instagram_business_content_publish"],
        access_token_ciphertext=TokenCipher(settings).encrypt("fake-long-token"),
        encryption_key_id="test-key",
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
        connection_status="CONNECTED",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_video_artifact_storage] = lambda: storage
    app.dependency_overrides[get_instagram_media_probe] = lambda: probe
    return settings, storage, probe, product_id, artifact_id, account


def run_worker(db: Session, settings, storage, probe, provider, worker_id: str):
    sessions = sessionmaker(bind=db.bind, expire_on_commit=False)
    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=settings,
        instagram_provider_factory=lambda _: provider,
        instagram_media_probe=probe,
        artifact_storage=storage,
    )
    return ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id=worker_id,
        heartbeat_interval_seconds=0.05,
    ).run_once()


def test_three_stage_queue_is_provider_free_and_restores_exact_task(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    settings, storage, probe, product_id, artifact_id, account = setup_runtime(
        db_session, tmp_path
    )
    metadata = {
        "social_account_id": account.id,
        "artifact_id": artifact_id,
        "title": "Local label",
        "description": "Safe caption",
        "tags": ["AI", "Demo"],
        "privacy_status": "public",
        "made_for_kids": False,
        "synthetic_media": True,
        "notify_subscribers": False,
        "share_to_feed": True,
    }
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/instagram/preflight",
        json=metadata,
    )
    assert checked.status_code == 200
    request = metadata | {
        "input_digest": checked.json()["input_digest"],
        "preflight_digest": checked.json()["preflight_digest"],
        "preflight_expires_at": checked.json()["expires_at"],
        "idempotency_key": "client-key-is-not-identity",
        "confirm_upload": True,
    }
    first = client.post(
        f"/api/v1/products/{product_id}/publishing/instagram", json=request
    )
    duplicate = client.post(
        f"/api/v1/products/{product_id}/publishing/instagram", json=request
    )
    assert first.status_code == duplicate.status_code == 201
    assert first.json()["job"]["id"] == duplicate.json()["job"]["id"]
    provider = FakeProvider()
    assert sum(provider.calls.values()) == 0
    result = run_worker(
        db_session, settings, storage, probe, provider, "instagram-submit-worker"
    )
    assert result.status == WorkerRunStatus.SUCCEEDED, (
        result,
        db_session.get(ExecutionJob, first.json()["job"]["id"]).status,
        provider.calls,
    )
    job = db_session.get(ExecutionJob, first.json()["job"]["id"])
    assert job is not None and job.result_entity_type == "publish_task"
    task_id = job.result_entity_id
    task = db_session.get(PublishTask, task_id)
    assert task is not None and task.status == "PROCESSING"
    assert provider.calls == {"create": 1, "upload": 1, "status": 0, "publish": 0}

    refresh = client.post(
        f"/api/v1/publish-tasks/{task.id}/instagram/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": "refresh-request-fixed-1",
        },
    )
    assert refresh.status_code == 201 and provider.calls["status"] == 0
    assert (
        run_worker(
            db_session, settings, storage, probe, provider, "instagram-refresh-worker"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    db_session.refresh(task)
    assert task.status == "READY_TO_PUBLISH" and provider.calls["status"] == 1

    preflight = client.post(
        f"/api/v1/publish-tasks/{task.id}/instagram/finalize-preflight",
        params={"product_id": product_id},
    )
    assert preflight.status_code == 200 and provider.calls["publish"] == 0
    final = client.post(
        f"/api/v1/publish-tasks/{task.id}/instagram/finalize",
        json={
            "product_id": product_id,
            "finalize_request_id": "finalize-request-fixed-1",
            "input_digest": preflight.json()["input_digest"],
            "preflight_digest": preflight.json()["preflight_digest"],
            "preflight_expires_at": preflight.json()["expires_at"],
            "confirm_public_publish": True,
        },
    )
    assert final.status_code == 201 and provider.calls["publish"] == 0
    assert (
        run_worker(
            db_session, settings, storage, probe, provider, "instagram-final-worker"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    db_session.refresh(task)
    assert task.status == "SUCCEEDED" and task.provider_video_id == "fake-final-media"
    assert provider.calls == {"create": 1, "upload": 1, "status": 1, "publish": 1}


def test_generic_queue_bypass_is_blocked_for_all_three_types(
    client: TestClient, db_session: Session
) -> None:
    before = db_session.query(ExecutionJob).count()
    for job_type in (
        "instagram.publish.submit.v1",
        "instagram.publish.refresh.v1",
        "instagram.publish.finalize.v1",
    ):
        response = client.post(
            "/api/v1/execution-jobs",
            json={
                "job_type": job_type,
                "source_type": "product",
                "source_id": 1,
                "input_digest": "a" * 64,
                "idempotency_key": f"blocked-{job_type}",
                "input_payload": {},
                "cost_confirmed": True,
            },
        )
        assert response.status_code == 409
    assert db_session.query(ExecutionJob).count() == before


@pytest.mark.parametrize(
    "changed_field",
    ["input_digest", "preflight_digest", "preflight_expires_at"],
)
def test_finalize_replay_rejects_changed_preflight_identity_without_new_job(
    changed_field: str,
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _, storage, _, product_id, artifact_id, account = setup_runtime(
        db_session, tmp_path
    )
    task = PublishTask(
        product_id=product_id,
        social_account_id=account.id,
        artifact_id=artifact_id,
        platform="instagram",
        idempotency_key=f"ready-instagram-{changed_field}",
        request_digest="b" * 64,
        preflight_digest="c" * 64,
        title="Ready local label",
        description="Ready caption",
        tags=["AI"],
        privacy_status="public",
        made_for_kids=False,
        synthetic_media=True,
        notify_subscribers=False,
        share_to_feed=False,
        status="READY_TO_PUBLISH",
        provider_container_id="fake-ready-container",
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    checked = client.post(
        f"/api/v1/publish-tasks/{task.id}/instagram/finalize-preflight",
        params={"product_id": product_id},
    ).json()
    request = {
        "product_id": product_id,
        "finalize_request_id": "same-finalize-request-id",
        "input_digest": checked["input_digest"],
        "preflight_digest": checked["preflight_digest"],
        "preflight_expires_at": checked["expires_at"],
        "confirm_public_publish": True,
    }
    original = client.post(
        f"/api/v1/publish-tasks/{task.id}/instagram/finalize", json=request
    )
    assert original.status_code == 201
    original_job_id = original.json()["job"]["id"]
    provider = FakeProvider()
    replay = client.post(
        f"/api/v1/publish-tasks/{task.id}/instagram/finalize", json=request
    )
    assert replay.status_code == 201
    assert replay.json()["reused"] is True
    assert replay.json()["job"]["id"] == original_job_id
    assert sum(provider.calls.values()) == 0
    before_jobs = db_session.query(ExecutionJob).count()
    if changed_field == "preflight_expires_at":
        request[changed_field] = (
            datetime.fromisoformat(str(request[changed_field])) + timedelta(seconds=1)
        ).isoformat()
    else:
        request[changed_field] = "d" * 64

    conflict = client.post(
        f"/api/v1/publish-tasks/{task.id}/instagram/finalize", json=request
    )

    assert conflict.status_code == 409
    assert db_session.query(ExecutionJob).count() == before_jobs
    assert db_session.get(ExecutionJob, original_job_id) is not None
    assert sum(provider.calls.values()) == 0
    assert storage is not None
