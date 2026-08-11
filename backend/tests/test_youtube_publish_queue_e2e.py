from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_youtube_provider
from app.execution.worker import WorkerRunStatus
from app.main import app
from app.models import ExecutionJob, PublishTask
from tests.test_social_publishing import (
    FakeYouTubeProvider,
    configure,
    connect_account,
    create_publishable_artifact,
    metadata,
    publish_request,
    run_youtube_worker,
)


def test_http_is_provider_free_and_two_workers_upload_once(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    settings, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    resolutions = 0

    def forbidden_http_provider() -> FakeYouTubeProvider:
        nonlocal resolutions
        resolutions += 1
        raise AssertionError("Queue HTTP resolved YouTube Provider")

    app.dependency_overrides[get_youtube_provider] = forbidden_http_provider
    payload = metadata(account.id, artifact_id)
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight",
        json=payload,
    )
    first = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, checked.json()),
    )
    duplicate = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, checked.json()),
    )

    assert checked.status_code == 200
    assert checked.json()["provider_calls"] == 0
    assert first.status_code == duplicate.status_code == 201
    assert first.json()["job"]["id"] == duplicate.json()["job"]["id"]
    assert duplicate.json()["reused"] is True
    assert resolutions == 0
    assert provider.session_calls == provider.media_calls == 0
    assert db_session.scalar(select(func.count(PublishTask.id))) == 1

    first_worker = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-e2e-1"
    )
    second_worker = run_youtube_worker(
        db_session, settings, storage, provider, "youtube-e2e-2"
    )

    assert first_worker.status == WorkerRunStatus.SUCCEEDED
    assert second_worker.status == WorkerRunStatus.NO_JOB
    assert provider.session_calls == provider.media_calls == 1
    db_session.expire_all()
    job = db_session.get(ExecutionJob, first.json()["job"]["id"])
    assert job.result_entity_type == "publish_task"
    assert db_session.get(PublishTask, job.result_entity_id) is not None


@pytest.mark.parametrize(
    "job_type",
    ["youtube.publish.submit.v1", "youtube.publish.refresh.v1"],
)
def test_generic_execution_job_creation_cannot_bypass_youtube_contract(
    client: TestClient, db_session: Session, job_type: str
) -> None:
    response = client.post(
        "/api/v1/execution-jobs",
        json={
            "job_type": job_type,
            "source_type": "product",
            "source_id": 1,
            "input_digest": "a" * 64,
            "idempotency_key": f"unsafe-{job_type}",
            "input_payload": {
                "token": "must-not-be-reflected",
                "session_uri": "must-not-be-reflected",
            },
            "cost_confirmed": True,
        },
    )

    assert response.status_code == 409
    assert "must-not-be-reflected" not in response.text
    assert "a" * 64 not in response.text
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 0
    assert db_session.scalar(select(func.count(PublishTask.id))) == 0


def test_refresh_http_is_provider_free_and_recovers_same_exact_task(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    settings, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    payload = metadata(account.id, artifact_id)
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight",
        json=payload,
    ).json()
    submit = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, checked),
    ).json()
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-e2e-submit"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    task_id = client.get(f"/api/v1/execution-jobs/{submit['job']['id']}").json()[
        "result_entity_id"
    ]
    resolutions = 0

    def forbidden_http_provider() -> FakeYouTubeProvider:
        nonlocal resolutions
        resolutions += 1
        raise AssertionError("Refresh HTTP resolved YouTube Provider")

    app.dependency_overrides[get_youtube_provider] = forbidden_http_provider
    refresh = client.post(
        f"/api/v1/publish-tasks/{task_id}/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": "explicit-refresh-e2e-0001",
        },
    )
    duplicate = client.post(
        f"/api/v1/publish-tasks/{task_id}/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": "explicit-refresh-e2e-0001",
        },
    )

    assert refresh.status_code == duplicate.status_code == 201
    assert refresh.json()["job"]["id"] == duplicate.json()["job"]["id"]
    assert resolutions == 0
    session_calls, media_calls = provider.session_calls, provider.media_calls
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-e2e-refresh"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    completed = client.get(
        f"/api/v1/execution-jobs/{refresh.json()['job']['id']}"
    ).json()
    assert completed["result_entity_type"] == "publish_task"
    assert completed["result_entity_id"] == task_id
    assert provider.status_calls == 1
    assert provider.session_calls == session_calls
    assert provider.media_calls == media_calls


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("title", "Changed private title"),
        ("description", "Changed private description"),
        ("tags", ["fake", "changed"]),
        ("tags", ["test", "fake"]),
        ("made_for_kids", True),
    ],
    ids=["title", "description", "tags-content", "tags-order", "made-for-kids"],
)
def test_submit_reuse_rejects_changed_metadata_for_original_input_digest(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    field: str,
    changed_value: object,
) -> None:
    provider = FakeYouTubeProvider()
    _, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    original = metadata(account.id, artifact_id)
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight",
        json=original,
    ).json()
    first = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(original, checked),
    )
    assert first.status_code == 201
    task = db_session.scalar(select(PublishTask))
    assert task is not None
    frozen = {
        "title": task.title,
        "description": task.description,
        "tags": list(task.tags),
        "made_for_kids": task.made_for_kids,
    }
    conflicting = original | {field: changed_value}
    request = publish_request(conflicting, checked) | {
        "input_digest": checked["input_digest"]
    }

    response = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=request,
    )

    assert response.status_code == 409
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 1
    assert db_session.scalar(select(func.count(PublishTask.id))) == 1
    db_session.refresh(task)
    assert task.title == frozen["title"]
    assert task.description == frozen["description"]
    assert task.tags == frozen["tags"]
    assert task.made_for_kids == frozen["made_for_kids"]
    assert provider.refresh_token_calls == 0
    assert provider.session_calls == 0
    assert provider.media_calls == 0
    assert provider.status_calls == 0


def test_submit_reuses_original_job_with_new_valid_preflight_expiry(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    _, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    payload = metadata(account.id, artifact_id)
    first_preflight = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight",
        json=payload,
    ).json()
    first = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, first_preflight),
    )
    second_preflight = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight",
        json=payload,
    ).json()
    replay = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, second_preflight)
        | {"idempotency_key": "different-client-key-is-not-queue-identity"},
    )

    assert first_preflight["input_digest"] == second_preflight["input_digest"]
    assert first_preflight["preflight_digest"] != second_preflight["preflight_digest"]
    assert first_preflight["expires_at"] != second_preflight["expires_at"]
    assert replay.status_code == 201
    assert replay.json()["reused"] is True
    assert replay.json()["job"]["id"] == first.json()["job"]["id"]
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == 1
    assert db_session.scalar(select(func.count(PublishTask.id))) == 1
    assert provider.refresh_token_calls == 0
    assert provider.session_calls == 0
    assert provider.media_calls == 0
    assert provider.status_calls == 0


@pytest.mark.parametrize("terminal_status", ["SUCCEEDED", "FAILED"])
def test_terminal_refresh_replay_reuses_job_but_new_request_is_rejected(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    terminal_status: str,
) -> None:
    provider = FakeYouTubeProvider()
    settings, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    payload = metadata(account.id, artifact_id)
    checked = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight",
        json=payload,
    ).json()
    submit = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, checked),
    ).json()
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-terminal-submit"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    task_id = client.get(f"/api/v1/execution-jobs/{submit['job']['id']}").json()[
        "result_entity_id"
    ]
    provider.video_status = terminal_status
    refresh_request_id = f"terminal-{terminal_status.lower()}-refresh-0001"
    first_refresh = client.post(
        f"/api/v1/publish-tasks/{task_id}/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": refresh_request_id,
        },
    )
    assert first_refresh.status_code == 201
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-terminal-refresh"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    before_jobs = db_session.scalar(select(func.count(ExecutionJob.id)))
    before_calls = (
        provider.refresh_token_calls,
        provider.session_calls,
        provider.media_calls,
        provider.status_calls,
    )

    replay = client.post(
        f"/api/v1/publish-tasks/{task_id}/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": refresh_request_id,
        },
    )
    new_request = client.post(
        f"/api/v1/publish-tasks/{task_id}/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": f"new-{terminal_status.lower()}-refresh-0002",
        },
    )

    assert replay.status_code == 201
    assert replay.json()["reused"] is True
    assert replay.json()["job"]["id"] == first_refresh.json()["job"]["id"]
    assert new_request.status_code == 409
    assert db_session.scalar(select(func.count(ExecutionJob.id))) == before_jobs == 2
    assert (
        provider.refresh_token_calls,
        provider.session_calls,
        provider.media_calls,
        provider.status_calls,
    ) == before_calls
    assert provider.status_calls == 1
