from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution.worker import WorkerRunStatus
from app.models import ExecutionJob, PublishTask, SocialAccount, VideoRenderArtifact
from app.providers.youtube_provider import (
    YouTubeProviderError,
    YouTubeUploadResult,
    YouTubeUploadUncertain,
)
from app.services.social_security import TokenCipher
from tests.test_social_publishing import (
    FakeYouTubeProvider,
    configure,
    connect_account,
    create_publishable_artifact,
    metadata,
    publish_request,
    run_youtube_worker,
)
from tests.test_video_render_service import create_video_project


class QueueYouTubeProvider(FakeYouTubeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.session_error: Exception | None = None
        self.media_error: Exception | None = None
        self.status_error: Exception | None = None

    async def initiate_upload_session(self, **kwargs: object) -> str:
        if self.session_error is not None:
            self.session_calls += 1
            raise self.session_error
        return await super().initiate_upload_session(**kwargs)

    async def upload_media(self, **kwargs: object) -> YouTubeUploadResult:
        if self.media_error is not None:
            self.media_calls += 1
            raise self.media_error
        return await super().upload_media(**kwargs)

    async def get_video_status(self, **kwargs: object):
        if self.status_error is not None:
            self.status_calls += 1
            raise self.status_error
        return await super().get_video_status(**kwargs)


def enqueue_submit(
    client: TestClient,
    db: Session,
    tmp_path: Path,
    provider: QueueYouTubeProvider,
) -> tuple[object, object, int, int, int]:
    settings, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db, storage)
    account = connect_account(client, db, product_id)
    payload = metadata(account.id, artifact_id)
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight",
        json=payload,
    )
    assert checked.status_code == 200
    queued = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, checked.json()),
    )
    assert queued.status_code == 201
    return settings, storage, product_id, account.id, queued.json()["job"]["id"]


def test_submit_handler_persists_exact_publish_task_result(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = QueueYouTubeProvider()
    settings, storage, product_id, _, job_id = enqueue_submit(
        client, db_session, tmp_path, provider
    )

    result = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-handler-success"
    )

    assert result.status == WorkerRunStatus.SUCCEEDED
    db_session.expire_all()
    job = db_session.get(ExecutionJob, job_id)
    assert job is not None
    assert job.provider_name == "youtube"
    assert job.result_entity_type == "publish_task"
    task = db_session.get(PublishTask, job.result_entity_id)
    assert task is not None
    assert task.product_id == product_id
    assert task.provider_video_id == "fake-video-001"
    assert task.status == "SUBMITTED"
    assert provider.session_calls == 1
    assert provider.media_calls == 1
    assert job.attempts[0].provider_call_count == 2
    assert job.attempts[0].external_submission_possible is True


@pytest.mark.parametrize(
    "mutation",
    [
        "account",
        "channel",
        "artifact",
        "render_task",
        "video_project",
        "copy_matrix",
        "metadata",
    ],
)
def test_changed_frozen_input_fails_before_provider(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    mutation: str,
) -> None:
    provider = QueueYouTubeProvider()
    settings, storage, product_id, account_id, job_id = enqueue_submit(
        client, db_session, tmp_path, provider
    )
    task = db_session.scalar(select(PublishTask))
    assert task is not None
    artifact = db_session.get(VideoRenderArtifact, task.artifact_id)
    assert artifact is not None
    render_task = artifact.video_render_task
    project = render_task.video_project
    if mutation == "account":
        db_session.get(SocialAccount, account_id).connection_status = "DISCONNECTED"
    elif mutation == "channel":
        db_session.get(SocialAccount, account_id).provider_account_id = "UC_CHANGED"
    elif mutation == "artifact":
        artifact.artifact_metadata = artifact.artifact_metadata | {"size_bytes": 999}
    elif mutation == "render_task":
        other = create_video_project(db_session)
        render_task.video_project_id = other.id
    elif mutation == "video_project":
        other = create_video_project(db_session)
        project.product_id = other.id
    elif mutation == "copy_matrix":
        other = create_video_project(db_session)
        project.copy_matrix_id = other.copy_matrix_id
    else:
        task.title = "Changed after enqueue"
    db_session.commit()

    result = run_youtube_worker(
        db_session, settings, storage, provider, f"youtube-frozen-{mutation}"
    )

    assert result.status == WorkerRunStatus.FAILED
    db_session.expire_all()
    assert db_session.get(ExecutionJob, job_id).status == "FAILED"
    assert provider.refresh_token_calls == 0
    assert provider.session_calls == 0
    assert provider.media_calls == 0
    assert provider.status_calls == 0
    assert product_id > 0


def test_token_decryption_failure_is_deterministic_before_provider(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = QueueYouTubeProvider()
    settings, storage, _, account_id, job_id = enqueue_submit(
        client, db_session, tmp_path, provider
    )
    db_session.get(SocialAccount, account_id).access_token_ciphertext = "invalid"
    db_session.commit()

    result = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-handler-token-invalid"
    )

    assert result.status == WorkerRunStatus.FAILED
    task = db_session.scalar(select(PublishTask))
    assert task.status == "FAILED"
    assert task.safe_error_code == "authorization_decryption_failed"
    assert db_session.get(ExecutionJob, job_id).status == "FAILED"
    assert provider.refresh_token_calls == provider.session_calls == 0
    assert provider.media_calls == 0


def test_token_refresh_failure_does_not_initialize_or_upload(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = QueueYouTubeProvider()
    settings, storage, _, account_id, _ = enqueue_submit(
        client, db_session, tmp_path, provider
    )
    provider.refresh_error = YouTubeProviderError(
        "authentication_failed", status_code=401
    )
    db_session.get(SocialAccount, account_id).token_expires_at = datetime.now(
        UTC
    ) - timedelta(seconds=1)
    db_session.commit()

    result = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-handler-refresh-failed"
    )

    assert result.status == WorkerRunStatus.FAILED
    assert provider.refresh_token_calls == 1
    assert provider.session_calls == provider.media_calls == 0


def test_session_initialization_failure_is_failed_without_media_upload(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = QueueYouTubeProvider()
    provider.session_error = YouTubeProviderError(
        "upload_session_rejected", status_code=400
    )
    settings, storage, _, _, _ = enqueue_submit(client, db_session, tmp_path, provider)

    result = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-handler-session-failed"
    )

    assert result.status == WorkerRunStatus.FAILED
    task = db_session.scalar(select(PublishTask))
    assert task.status == "FAILED"
    assert task.safe_error_code == "upload_session_rejected"
    assert provider.session_calls == 1
    assert provider.media_calls == 0


def test_media_exception_is_submit_unknown_and_never_retried(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = QueueYouTubeProvider()
    provider.media_error = YouTubeUploadUncertain("fake media outcome unknown")
    settings, storage, product_id, _, job_id = enqueue_submit(
        client, db_session, tmp_path, provider
    )

    first = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-handler-media-unknown"
    )
    second = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-handler-restarted"
    )
    retry = client.post(
        f"/api/v1/execution-jobs/{job_id}/retry",
        json={"retry_confirmed": True},
    )

    assert first.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert second.status == WorkerRunStatus.NO_JOB
    assert retry.status_code == 409
    task = db_session.scalar(select(PublishTask))
    assert task.status == "SUBMIT_UNKNOWN"
    assert task.uncertain is True
    assert task.product_id == product_id
    assert provider.session_calls == provider.media_calls == 1
    serialized = json.dumps(client.get(f"/api/v1/execution-jobs/{job_id}").json())
    assert "upload.example" not in serialized
    assert "fake-access-token" not in serialized
    assert "fake media outcome unknown" not in serialized


def test_restarted_worker_never_uploads_when_session_was_already_persisted(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = QueueYouTubeProvider()
    settings, storage, _, _, _ = enqueue_submit(client, db_session, tmp_path, provider)
    task = db_session.scalar(select(PublishTask))
    task.resumable_session_ciphertext = TokenCipher(settings).encrypt(
        "https://upload.example/persisted-session"
    )
    task.status = "UPLOADING"
    db_session.commit()

    first = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-session-recovery"
    )
    second = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-session-recovery-restart"
    )

    assert first.status == WorkerRunStatus.SUBMIT_UNKNOWN
    assert second.status == WorkerRunStatus.NO_JOB
    assert provider.refresh_token_calls == 0
    assert provider.session_calls == 0
    assert provider.media_calls == 0


def test_queued_submit_executes_after_original_preflight_expiry(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = QueueYouTubeProvider()
    settings, storage, _, _, job_id = enqueue_submit(
        client, db_session, tmp_path, provider
    )
    job = db_session.get(ExecutionJob, job_id)
    task = db_session.scalar(select(PublishTask))
    payload = dict(job.input_payload)
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    material = {
        "contract": "youtube-private-preflight-v1",
        "input_digest": payload["frozen_input_digest"],
        "expires_at": expired_at.isoformat(),
    }
    digest = hashlib.sha256(
        json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    payload["preflight_expires_at"] = expired_at.isoformat()
    payload["preflight_digest"] = digest
    job.input_payload = payload
    task.preflight_digest = digest
    db_session.commit()

    result = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-expired-preflight"
    )

    assert result.status == WorkerRunStatus.SUCCEEDED
    assert provider.session_calls == provider.media_calls == 1


@pytest.mark.parametrize("provider_status", ["PROCESSING", "SUCCEEDED", "FAILED"])
def test_refresh_handler_queries_once_and_saves_exact_task(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    provider_status: str,
) -> None:
    provider = QueueYouTubeProvider()
    settings, storage, product_id, _, submit_job_id = enqueue_submit(
        client, db_session, tmp_path, provider
    )
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-refresh-setup"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    submit_job = client.get(f"/api/v1/execution-jobs/{submit_job_id}").json()
    task_id = submit_job["result_entity_id"]
    provider.video_status = provider_status
    queued = client.post(
        f"/api/v1/publish-tasks/{task_id}/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": f"refresh-{provider_status.lower()}-00001",
        },
    )
    assert queued.status_code == 201
    session_calls = provider.session_calls
    media_calls = provider.media_calls

    result = run_youtube_worker(
        db_session, settings, storage, provider, f"youtube-refresh-{provider_status}"
    )

    assert result.status == WorkerRunStatus.SUCCEEDED
    db_session.expire_all()
    refresh_job = db_session.get(ExecutionJob, queued.json()["job"]["id"])
    assert refresh_job.result_entity_id == task_id
    assert refresh_job.result_entity_type == "publish_task"
    assert db_session.get(PublishTask, task_id).status == provider_status
    assert provider.status_calls == 1
    assert provider.session_calls == session_calls
    assert provider.media_calls == media_calls


@pytest.mark.parametrize("mutation", ["product", "account", "provider_video_id"])
def test_refresh_identity_change_fails_before_status_query(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    mutation: str,
) -> None:
    provider = QueueYouTubeProvider()
    settings, storage, product_id, account_id, submit_job_id = enqueue_submit(
        client, db_session, tmp_path, provider
    )
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-refresh-invalid-setup"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    task_id = client.get(f"/api/v1/execution-jobs/{submit_job_id}").json()[
        "result_entity_id"
    ]
    queued = client.post(
        f"/api/v1/publish-tasks/{task_id}/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": f"refresh-invalid-{mutation}-0001",
        },
    )
    assert queued.status_code == 201
    task = db_session.get(PublishTask, task_id)
    if mutation == "product":
        task.product_id = create_video_project(db_session).id
    elif mutation == "account":
        task.social_account_id = account_id + 99999
    else:
        task.provider_video_id = "changed-provider-id"
    db_session.commit()
    status_calls = provider.status_calls

    result = run_youtube_worker(
        db_session, settings, storage, provider, f"youtube-refresh-invalid-{mutation}"
    )

    assert result.status == WorkerRunStatus.FAILED
    assert provider.status_calls == status_calls


def test_refresh_query_failure_is_failed_and_never_uploads(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = QueueYouTubeProvider()
    settings, storage, product_id, _, submit_job_id = enqueue_submit(
        client, db_session, tmp_path, provider
    )
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-refresh-error-setup"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    task_id = client.get(f"/api/v1/execution-jobs/{submit_job_id}").json()[
        "result_entity_id"
    ]
    queued = client.post(
        f"/api/v1/publish-tasks/{task_id}/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": "refresh-query-failure-0001",
        },
    )
    provider.status_error = YouTubeProviderError(
        "status_refresh_unavailable", status_code=503
    )
    session_calls, media_calls = provider.session_calls, provider.media_calls

    result = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-refresh-query-error"
    )

    assert result.status == WorkerRunStatus.FAILED
    assert (
        client.get(f"/api/v1/execution-jobs/{queued.json()['job']['id']}").json()[
            "status"
        ]
        == "FAILED"
    )
    assert provider.status_calls == 1
    assert provider.session_calls == session_calls
    assert provider.media_calls == media_calls
