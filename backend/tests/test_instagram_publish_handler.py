from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.execution.worker import WorkerRunStatus
from app.models import ExecutionJob, PublishTask
from tests.test_instagram_publish_queue_e2e import (
    FakeProvider,
    run_worker,
    setup_runtime,
)


def enqueue_submit(client, product_id, artifact_id, account_id):
    metadata = {
        "social_account_id": account_id,
        "artifact_id": artifact_id,
        "title": "Local label",
        "description": "Safe",
        "tags": ["AI"],
        "privacy_status": "public",
        "made_for_kids": False,
        "synthetic_media": True,
        "notify_subscribers": False,
        "share_to_feed": False,
    }
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/instagram/preflight", json=metadata
    ).json()
    return client.post(
        f"/api/v1/products/{product_id}/publishing/instagram",
        json=metadata
        | {
            "input_digest": checked["input_digest"],
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
            "idempotency_key": "ignored-client-key",
            "confirm_upload": True,
        },
    ).json()["job"]["id"]


def test_create_boundary_failure_is_submit_unknown_and_not_retried(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    settings, storage, probe, product_id, artifact_id, account = setup_runtime(
        db_session, tmp_path
    )
    job_id = enqueue_submit(client, product_id, artifact_id, account.id)
    provider = FakeProvider()

    async def uncertain(**kwargs):
        provider.calls["create"] += 1
        raise RuntimeError("fake uncertain create")

    provider.create_resumable_reel_container = uncertain
    result = run_worker(
        db_session, settings, storage, probe, provider, "instagram-unknown-worker"
    )
    assert result.status == WorkerRunStatus.SUBMIT_UNKNOWN
    db_session.expire_all()
    job = db_session.get(ExecutionJob, job_id)
    task = db_session.get(
        PublishTask, job.result_entity_id or job.input_payload["publish_task_id"]
    )
    assert job.status == "SUBMIT_UNKNOWN" and job.max_attempts == 1
    assert task.status == "SUBMIT_UNKNOWN" and task.uncertain is True
    assert provider.calls == {"create": 1, "upload": 0, "status": 0, "publish": 0}
    assert (
        run_worker(
            db_session, settings, storage, probe, provider, "instagram-restart-worker"
        ).status
        == WorkerRunStatus.NO_JOB
    )
    assert provider.calls["create"] == 1
