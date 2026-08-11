from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_video_artifact_storage, get_youtube_provider
from app.core.config import Settings, _local_env_file, get_settings
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.main import app
from app.models import OAuthSession, PublishTask, SocialAccount, VideoRenderArtifact
from app.providers.youtube_provider import (
    YOUTUBE_SCOPES,
    OAuthTokens,
    YouTubeChannel,
    YouTubeProvider,
    YouTubeProviderError,
    YouTubeUploadResult,
    YouTubeUploadUncertain,
    YouTubeVideoStatus,
)
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from app.services.video_render_service import VideoRenderService
from tests.test_video_render_service import create_video_project, render_request

ACCESS_TOKEN = "fake-access-token-never-real"
REFRESH_TOKEN = "fake-refresh-token-never-real"


class FakeYouTubeProvider:
    def __init__(self) -> None:
        self.authorization_calls = 0
        self.exchange_calls = 0
        self.channel_calls = 0
        self.upload_calls = 0
        self.session_calls = 0
        self.media_calls = 0
        self.refresh_token_calls = 0
        self.status_calls = 0
        self.revoke_calls = 0
        self.uncertain_upload = False
        self.video_status = "SUCCEEDED"
        self.refresh_error: YouTubeProviderError | None = None

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        self.authorization_calls += 1
        return f"https://accounts.example/authorize?state={state}&challenge={code_challenge}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> OAuthTokens:
        self.exchange_calls += 1
        assert code == "fake-code"
        assert len(code_verifier) >= 43
        return OAuthTokens(
            access_token=ACCESS_TOKEN,
            refresh_token=REFRESH_TOKEN,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=YOUTUBE_SCOPES,
        )

    async def get_channel(self, access_token: str) -> YouTubeChannel:
        self.channel_calls += 1
        assert access_token == ACCESS_TOKEN
        return YouTubeChannel("UC_FAKE_CHANNEL", "Fake Channel")

    async def revoke_token(self, token: str) -> None:
        self.revoke_calls += 1
        assert token in {ACCESS_TOKEN, REFRESH_TOKEN}

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        self.refresh_token_calls += 1
        assert refresh_token == REFRESH_TOKEN
        if self.refresh_error is not None:
            raise self.refresh_error
        return OAuthTokens(
            access_token="fake-refreshed-access",
            refresh_token=REFRESH_TOKEN,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=YOUTUBE_SCOPES,
        )

    async def upload_video(self, **kwargs: object) -> YouTubeUploadResult:
        self.upload_calls += 1
        assert kwargs["access_token"] in {ACCESS_TOKEN, "fake-refreshed-access"}
        assert kwargs["made_for_kids"] is False
        assert Path(str(kwargs["path"])).is_file()
        if self.uncertain_upload:
            raise YouTubeUploadUncertain("https://upload.example/fake-session")
        return YouTubeUploadResult("fake-video-001")

    async def initiate_upload_session(self, **kwargs: object) -> str:
        self.session_calls += 1
        assert kwargs["access_token"] in {ACCESS_TOKEN, "fake-refreshed-access"}
        assert Path(str(kwargs["path"])).is_file()
        return "https://upload.example/fake-session"

    async def upload_media(self, **kwargs: object) -> YouTubeUploadResult:
        self.media_calls += 1
        assert kwargs["access_token"] in {ACCESS_TOKEN, "fake-refreshed-access"}
        assert kwargs["session_uri"] == "https://upload.example/fake-session"
        assert Path(str(kwargs["path"])).is_file()
        if self.uncertain_upload:
            raise YouTubeUploadUncertain("fake uncertain upload")
        return YouTubeUploadResult("fake-video-001")

    async def get_video_status(
        self, *, access_token: str, video_id: str
    ) -> YouTubeVideoStatus:
        self.status_calls += 1
        assert access_token in {ACCESS_TOKEN, "fake-refreshed-access"}
        assert video_id == "fake-video-001"
        return YouTubeVideoStatus(self.video_status)


class ScriptedAsyncClient:
    post_effects: list[httpx.Response | BaseException] = []
    put_effects: list[httpx.Response | BaseException] = []
    post_calls = 0
    put_calls = 0

    def __init__(self, **kwargs: object) -> None:
        del kwargs

    async def __aenter__(self) -> ScriptedAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        del url, kwargs
        type(self).post_calls += 1
        return self._result(type(self).post_effects.pop(0))

    async def put(self, url: str, **kwargs: object) -> httpx.Response:
        del url, kwargs
        type(self).put_calls += 1
        return self._result(type(self).put_effects.pop(0))

    @classmethod
    def reset(
        cls,
        *,
        posts: list[httpx.Response | BaseException],
        puts: list[httpx.Response | BaseException] | None = None,
    ) -> None:
        cls.post_effects = list(posts)
        cls.put_effects = list(puts or [])
        cls.post_calls = 0
        cls.put_calls = 0

    @staticmethod
    def _result(effect: httpx.Response | BaseException) -> httpx.Response:
        if isinstance(effect, BaseException):
            raise effect
        return effect


def enabled_settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        enable_social_account_binding=True,
        enable_youtube_publishing=True,
        google_oauth_client_id="fake-client-id",
        google_oauth_client_secret="fake-client-secret",
        google_oauth_redirect_uri=(
            "http://127.0.0.1:8000/api/v1/social-accounts/youtube/callback"
        ),
        social_token_encryption_key=Fernet.generate_key().decode("ascii"),
        video_artifact_storage_root=str(root),
    )


def configure(
    root: Path, provider: FakeYouTubeProvider
) -> tuple[Settings, LocalVideoArtifactStorage]:
    settings = enabled_settings(root)
    storage = LocalVideoArtifactStorage(root, 1_000_000)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_youtube_provider] = lambda: provider
    app.dependency_overrides[get_video_artifact_storage] = lambda: storage
    return settings, storage


def create_publishable_artifact(
    db: Session, storage: LocalVideoArtifactStorage
) -> tuple[int, int]:
    project = create_video_project(db)
    service = VideoRenderService(db)
    task = service.create_render_task(project.id, render_request("social-render"))
    service.transition_status(task.id, "SUBMITTED")
    task = service.transition_status(task.id, "SUCCEEDED")
    stored = storage.store(
        task_id=task.id,
        content=b"fake-video-content",
        content_type="video/mp4",
    )
    artifact = VideoRenderArtifact(
        video_render_task_id=task.id,
        storage_path=stored.relative_path,
        artifact_metadata={
            "content_type": stored.content_type,
            "size_bytes": stored.size_bytes,
            "sha256": stored.sha256,
        },
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return project.id, artifact.id


def connect_account(client: TestClient, db: Session, product_id: int) -> SocialAccount:
    response = client.post(
        "/api/v1/social-accounts/youtube/connect", json={"product_id": product_id}
    )
    assert response.status_code == 200
    state = parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]
    callback = client.get(
        "/api/v1/social-accounts/youtube/callback",
        params={"state": state, "code": "fake-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    return db.scalar(select(SocialAccount))


def metadata(account_id: int, artifact_id: int) -> dict[str, object]:
    return {
        "social_account_id": account_id,
        "artifact_id": artifact_id,
        "title": "Fake private upload",
        "description": "Fake-only acceptance test",
        "tags": ["fake", "test"],
        "privacy_status": "private",
        "made_for_kids": False,
        "synthetic_media": True,
        "notify_subscribers": False,
    }


def publish_request(
    payload: dict[str, object], preflight: dict[str, object]
) -> dict[str, object]:
    return payload | {
        "input_digest": preflight["input_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "preflight_expires_at": preflight["expires_at"],
        "idempotency_key": "fake-client-key-not-used-for-queue-identity",
        "confirm_upload": True,
    }


def run_youtube_worker(
    db: Session,
    settings: Settings,
    storage: LocalVideoArtifactStorage,
    provider: FakeYouTubeProvider | YouTubeProvider,
    worker_id: str,
):
    sessions = sessionmaker(bind=db.bind, expire_on_commit=False)
    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=settings,
        youtube_provider_factory=lambda _: provider,
        artifact_storage=storage,
    )
    return ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id=worker_id,
        heartbeat_interval_seconds=0.05,
    ).run_once()


def test_gates_default_off_before_provider_resolution(
    client: TestClient, db_session: Session
) -> None:
    project = create_video_project(db_session)
    resolutions = 0

    def forbidden_provider() -> FakeYouTubeProvider:
        nonlocal resolutions
        resolutions += 1
        raise AssertionError("Provider resolved behind a closed gate")

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_youtube_provider] = forbidden_provider

    connect = client.post(
        "/api/v1/social-accounts/youtube/connect", json={"product_id": project.id}
    )
    publish = client.post(
        f"/api/v1/products/{project.id}/publishing/youtube",
        json=metadata(1, 1)
        | {
            "input_digest": "0" * 64,
            "preflight_digest": "0" * 64,
            "preflight_expires_at": (
                datetime.now(UTC) + timedelta(minutes=5)
            ).isoformat(),
            "idempotency_key": "fake-key-closed",
            "confirm_upload": True,
        },
    )

    assert connect.status_code == 503
    assert publish.status_code == 503
    assert resolutions == 0


def test_artifact_candidates_are_local_read_only_when_publishing_gate_is_off(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    provider_resolutions = 0

    def forbidden_provider() -> FakeYouTubeProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Read-only candidate GET resolved YouTube Provider")

    settings = enabled_settings(tmp_path).model_copy(
        update={"enable_youtube_publishing": False}
    )
    storage = LocalVideoArtifactStorage(tmp_path, 1_000_000)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_youtube_provider] = forbidden_provider
    app.dependency_overrides[get_video_artifact_storage] = lambda: storage
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    artifact = db_session.get(VideoRenderArtifact, artifact_id)
    assert artifact is not None
    task = artifact.video_render_task
    project = task.video_project
    write_statements: list[str] = []

    def record_writes(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        operation = statement.lstrip().split(None, 1)[0].upper()
        if operation in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            write_statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", record_writes)
    try:
        candidates = client.get(
            f"/api/v1/products/{product_id}/publishing/youtube/artifacts"
        )
        wrong_product = client.get(
            "/api/v1/products/999999/publishing/youtube/artifacts"
        )
        preflight = client.post(
            f"/api/v1/products/{product_id}/publishing/youtube/preflight",
            json=metadata(1, artifact_id),
        )
        publish = client.post(
            f"/api/v1/products/{product_id}/publishing/youtube",
            json=metadata(1, artifact_id)
            | {
                "input_digest": "0" * 64,
                "preflight_digest": "0" * 64,
                "preflight_expires_at": (
                    datetime.now(UTC) + timedelta(minutes=5)
                ).isoformat(),
                "idempotency_key": "closed-gate-local-candidate-test",
                "confirm_upload": True,
            },
        )
    finally:
        event.remove(bind, "before_cursor_execute", record_writes)

    assert candidates.status_code == 200
    assert candidates.json() == [
        {
            "artifact_id": artifact.id,
            "render_task_id": task.id,
            "video_project_id": project.id,
            "copy_matrix_id": project.copy_matrix_id,
            "content_type": "video/mp4",
            "size_bytes": len(b"fake-video-content"),
            "sha256": artifact.artifact_metadata["sha256"],
            "created_at": artifact.created_at.isoformat(),
        }
    ]
    assert wrong_product.status_code == 404
    assert preflight.status_code == 503
    assert publish.status_code == 503
    assert provider_resolutions == 0
    assert write_statements == []
    assert db_session.scalar(select(func.count()).select_from(PublishTask)) == 0


@pytest.mark.parametrize(
    "invalid_case",
    ["wrong_product", "missing_file", "unsafe_path"],
)
def test_invalid_artifacts_are_not_local_candidates(
    invalid_case: str,
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    provider_resolutions = 0

    def forbidden_provider() -> FakeYouTubeProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Invalid candidate GET resolved YouTube Provider")

    settings = enabled_settings(tmp_path).model_copy(
        update={"enable_youtube_publishing": False}
    )
    storage = LocalVideoArtifactStorage(tmp_path, 1_000_000)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_youtube_provider] = forbidden_provider
    app.dependency_overrides[get_video_artifact_storage] = lambda: storage
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    artifact = db_session.get(VideoRenderArtifact, artifact_id)
    assert artifact is not None
    request_product_id = product_id

    if invalid_case == "wrong_product":
        request_product_id = create_video_project(db_session).product_id
    elif invalid_case == "missing_file":
        storage.resolve(artifact.storage_path or "")[0].unlink()
    elif invalid_case == "unsafe_path":
        artifact.storage_path = "../outside.mp4"
        db_session.commit()
    response = client.get(
        f"/api/v1/products/{request_product_id}/publishing/youtube/artifacts"
    )

    assert response.status_code == 200
    assert response.json() == []
    assert provider_resolutions == 0


def test_oauth_state_is_one_time_and_tokens_are_encrypted(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    configure(tmp_path, provider)
    project = create_video_project(db_session)
    connect = client.post(
        "/api/v1/social-accounts/youtube/connect", json={"product_id": project.id}
    )
    state = parse_qs(urlparse(connect.json()["authorization_url"]).query)["state"][0]
    oauth_session = db_session.scalar(select(OAuthSession))

    assert oauth_session.state_digest != state
    assert oauth_session.consumed_at is None
    other_browser = TestClient(app)
    try:
        cross_session = other_browser.get(
            "/api/v1/social-accounts/youtube/callback",
            params={"state": state, "code": "fake-code"},
            follow_redirects=False,
        )
    finally:
        other_browser.close()
    first = client.get(
        "/api/v1/social-accounts/youtube/callback",
        params={"state": state, "code": "fake-code"},
        follow_redirects=False,
    )
    replay = client.get(
        "/api/v1/social-accounts/youtube/callback",
        params={"state": state, "code": "fake-code"},
        follow_redirects=False,
    )
    account = db_session.scalar(select(SocialAccount))

    assert cross_session.status_code == 400
    assert first.status_code == 303
    assert first.headers["location"].endswith("/products?youtube_oauth=connected")
    assert replay.status_code == 409
    assert oauth_session.consumed_at is not None
    assert account.access_token_ciphertext != ACCESS_TOKEN
    assert account.refresh_token_ciphertext != REFRESH_TOKEN
    database_text = " ".join(
        [account.access_token_ciphertext or "", account.refresh_token_ciphertext or ""]
    )
    assert ACCESS_TOKEN not in database_text
    assert REFRESH_TOKEN not in database_text
    assert provider.exchange_calls == 1
    assert provider.channel_calls == 1


def test_expired_and_denied_oauth_are_safe(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    configure(tmp_path, provider)
    project = create_video_project(db_session)
    connect = client.post(
        "/api/v1/social-accounts/youtube/connect", json={"product_id": project.id}
    )
    state = parse_qs(urlparse(connect.json()["authorization_url"]).query)["state"][0]
    oauth_session = db_session.scalar(select(OAuthSession))
    oauth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    expired = client.get(
        "/api/v1/social-accounts/youtube/callback",
        params={"state": state, "code": "fake-code"},
        follow_redirects=False,
    )
    assert expired.status_code == 410

    second = client.post(
        "/api/v1/social-accounts/youtube/connect", json={"product_id": project.id}
    )
    second_state = parse_qs(urlparse(second.json()["authorization_url"]).query)[
        "state"
    ][0]
    denied = client.get(
        "/api/v1/social-accounts/youtube/callback",
        params={"state": second_state, "error": "access_denied"},
        follow_redirects=False,
    )
    assert denied.status_code == 303
    assert denied.headers["location"].endswith("/products?youtube_oauth=denied")
    assert provider.exchange_calls == 0


def test_preflight_is_provider_free_and_database_read_only(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    _, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    before = db_session.scalar(select(func.count()).select_from(PublishTask))

    response = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight",
        json=metadata(account.id, artifact_id),
    )
    after = db_session.scalar(select(func.count()).select_from(PublishTask))

    assert response.status_code == 200
    assert response.json()["status"] == "READY"
    assert response.json()["provider_calls"] == 0
    assert response.json()["database_writes"] == 0
    assert before == after == 0
    assert provider.upload_calls == 0
    assert provider.refresh_token_calls == 0


def test_preflight_requires_made_for_kids_and_exact_product(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    _, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    payload = metadata(account.id, artifact_id) | {"made_for_kids": None}
    blocked = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight",
        json=payload,
    )
    other = create_video_project(db_session)
    cross_product = client.post(
        f"/api/v1/products/{other.id}/publishing/youtube/preflight",
        json=metadata(account.id, artifact_id),
    )

    assert blocked.status_code == 200
    assert blocked.json()["status"] == "BLOCKED"
    assert cross_product.status_code == 404


def test_publish_is_idempotent_and_refreshes_same_task(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    settings, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    payload = metadata(account.id, artifact_id)
    preflight = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight", json=payload
    ).json()
    execution = publish_request(payload, preflight)

    first = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube", json=execution
    )
    duplicate = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube", json=execution
    )
    job_id = first.json()["job"]["id"]
    assert provider.session_calls == provider.media_calls == 0
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-submit-idempotent"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    completed_job = client.get(f"/api/v1/execution-jobs/{job_id}").json()
    task_id = completed_job["result_entity_id"]
    recovered = client.get(
        f"/api/v1/publish-tasks/{task_id}",
        params={"product_id": product_id},
    )
    refreshed = client.post(
        f"/api/v1/publish-tasks/{task_id}/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": "fake-refresh-request-0001",
        },
    )
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-refresh-idempotent"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )
    refreshed_task = client.get(
        f"/api/v1/publish-tasks/{task_id}", params={"product_id": product_id}
    )

    assert first.status_code == 201
    assert completed_job["result_entity_type"] == "publish_task"
    assert duplicate.status_code == 201
    assert duplicate.json()["reused"] is True
    assert recovered.json()["id"] == task_id
    assert refreshed.status_code == 201
    assert refreshed_task.json()["id"] == task_id
    assert refreshed_task.json()["status"] == "SUCCEEDED"
    assert provider.session_calls == 1
    assert provider.media_calls == 1
    assert provider.status_calls == 1
    assert db_session.scalar(select(func.count()).select_from(PublishTask)) == 1


def test_uncertain_upload_never_retries(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    provider.uncertain_upload = True
    settings, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    payload = metadata(account.id, artifact_id)
    preflight = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight", json=payload
    ).json()
    execution = publish_request(payload, preflight)
    first = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube", json=execution
    )
    duplicate = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube", json=execution
    )
    job_id = first.json()["job"]["id"]
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-submit-unknown"
        ).status
        == WorkerRunStatus.SUBMIT_UNKNOWN
    )
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-submit-no-retry"
        ).status
        == WorkerRunStatus.NO_JOB
    )
    job = client.get(f"/api/v1/execution-jobs/{job_id}").json()
    task = db_session.scalar(select(PublishTask))
    assert task is not None
    task_id = task.id
    refresh = client.post(
        f"/api/v1/publish-tasks/{task_id}/refresh",
        json={
            "product_id": product_id,
            "refresh_request_id": "fake-refresh-request-0002",
        },
    )

    assert first.status_code == 201
    assert job["status"] == "SUBMIT_UNKNOWN"
    assert duplicate.json()["reused"] is True
    assert refresh.status_code == 409
    assert provider.session_calls == 1
    assert provider.media_calls == 1
    assert task.resumable_session_ciphertext is not None
    assert "upload.example" not in task.resumable_session_ciphertext


def test_product_identity_and_preflight_expiry_fail_closed(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    _, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    other_product = create_video_project(db_session)

    wrong_account = client.get(
        f"/api/v1/social-accounts/{account.id}",
        params={"product_id": other_product.id},
    )
    wrong_disconnect = client.post(
        f"/api/v1/social-accounts/{account.id}/disconnect",
        json={
            "product_id": other_product.id,
            "revoke_google_authorization": False,
            "confirm_disconnect": True,
        },
    )
    payload = metadata(account.id, artifact_id)
    preflight = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight", json=payload
    ).json()
    expired = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=payload
        | {
            "input_digest": preflight["input_digest"],
            "preflight_digest": preflight["preflight_digest"],
            "preflight_expires_at": (
                datetime.now(UTC) - timedelta(seconds=1)
            ).isoformat(),
            "idempotency_key": "fake-expired-preflight",
            "confirm_upload": True,
        },
    )

    assert wrong_account.status_code == 404
    assert wrong_disconnect.status_code == 404
    assert expired.status_code == 409
    assert provider.upload_calls == 0
    assert provider.revoke_calls == 0
    assert db_session.scalar(select(func.count()).select_from(PublishTask)) == 0


def test_disconnect_requires_confirmation_and_can_revoke(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    configure(tmp_path, provider)
    project = create_video_project(db_session)
    account = connect_account(client, db_session, project.id)
    missing_confirmation = client.post(
        f"/api/v1/social-accounts/{account.id}/disconnect",
        json={
            "product_id": project.id,
            "revoke_google_authorization": True,
        },
    )
    disconnected = client.post(
        f"/api/v1/social-accounts/{account.id}/disconnect",
        json={
            "revoke_google_authorization": True,
            "product_id": project.id,
            "confirm_disconnect": True,
        },
    )

    assert missing_confirmation.status_code == 422
    assert disconnected.status_code == 200
    assert disconnected.json()["google_authorization_revoked"] is True
    assert disconnected.json()["account"]["connection_status"] == "DISCONNECTED"
    assert account.access_token_ciphertext is None
    assert account.refresh_token_ciphertext is None
    assert provider.revoke_calls == 1


def test_oauth_cookie_returns_to_callback_on_127_host(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    settings, _ = configure(tmp_path, provider)
    project = create_video_project(db_session)
    client.base_url = httpx.URL("http://127.0.0.1:8000")
    connect = client.post(
        "/api/v1/social-accounts/youtube/connect",
        json={"product_id": project.id},
    )
    state = parse_qs(urlparse(connect.json()["authorization_url"]).query)["state"][0]
    callback = client.get(
        "/api/v1/social-accounts/youtube/callback",
        params={"state": state, "code": "fake-code"},
        follow_redirects=False,
    )

    assert connect.status_code == 200
    assert "social_oauth_browser=" in connect.headers["set-cookie"]
    assert callback.status_code == 303
    assert urlparse(settings.google_oauth_redirect_uri or "").hostname == "127.0.0.1"
    assert provider.exchange_calls == 1


def test_pytest_and_fake_smoke_disable_dotenv_from_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("ENABLE_YOUTUBE_PUBLISHING=true\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ENABLE_YOUTUBE_PUBLISHING", raising=False)

    assert _local_env_file() is None
    assert Settings(_env_file=_local_env_file()).enable_youtube_publishing is False

    monkeypatch.setenv("SOCIALPILOT_DISABLE_DOTENV", "true")
    assert _local_env_file() is None


def test_expired_token_refreshes_before_upload(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    settings, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    payload = metadata(account.id, artifact_id)
    preflight = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight", json=payload
    ).json()
    account.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    published = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, preflight),
    )
    assert published.status_code == 201
    assert provider.refresh_token_calls == provider.session_calls == 0
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-token-refresh-success"
        ).status
        == WorkerRunStatus.SUCCEEDED
    )

    db_session.refresh(account)
    assert provider.refresh_token_calls == 1
    assert provider.session_calls == 1
    assert provider.media_calls == 1
    assert account.access_token_ciphertext != "fake-refreshed-access"


def test_token_refresh_failure_is_failed_before_upload(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    provider.refresh_error = YouTubeProviderError(
        "authentication_failed", status_code=401
    )
    settings, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    payload = metadata(account.id, artifact_id)
    preflight = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight", json=payload
    ).json()
    account.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    published = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, preflight),
    )
    job_id = published.json()["job"]["id"]
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-token-refresh-failure"
        ).status
        == WorkerRunStatus.FAILED
    )

    task = db_session.scalar(select(PublishTask))
    assert task is not None
    assert published.status_code == 201
    assert client.get(f"/api/v1/execution-jobs/{job_id}").json()["status"] == "FAILED"
    assert task.status == "FAILED"
    assert task.uncertain is False
    assert task.safe_error_code == "token_refresh_authentication_failed"
    assert provider.refresh_token_calls == 1
    assert provider.session_calls == 0
    assert provider.media_calls == 0


def test_token_decryption_failure_is_failed_before_upload(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    provider = FakeYouTubeProvider()
    settings, storage = configure(tmp_path, provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    payload = metadata(account.id, artifact_id)
    preflight = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight", json=payload
    ).json()
    account.access_token_ciphertext = "invalid-ciphertext"
    db_session.commit()

    published = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, preflight),
    )
    assert published.status_code == 201
    assert (
        run_youtube_worker(
            db_session, settings, storage, provider, "youtube-decryption-failure"
        ).status
        == WorkerRunStatus.FAILED
    )

    task = db_session.scalar(select(PublishTask))
    assert task is not None
    assert task.status == "FAILED"
    assert task.uncertain is False
    assert task.safe_error_code == "authorization_decryption_failed"
    assert provider.refresh_token_calls == 0
    assert provider.session_calls == 0
    assert provider.media_calls == 0


@pytest.mark.parametrize(
    ("status", "safe_code"),
    [
        (401, "authentication_failed"),
        (403, "permission_denied"),
        (408, "request_timeout"),
        (429, "rate_limited"),
        (500, "provider_service_error"),
        (503, "provider_service_error"),
    ],
)
def test_provider_http_errors_have_safe_classification(
    status: int, safe_code: str
) -> None:
    response = httpx.Response(
        status,
        request=httpx.Request("POST", "https://provider.invalid/fake"),
    )
    with pytest.raises(YouTubeProviderError) as raised:
        YouTubeProvider._raise_for_status(response, phase="upload_session")

    assert raised.value.safe_error_code == f"upload_session_{safe_code}"
    assert raised.value.status_code == status
    assert raised.value.uncertain is False


def test_revoke_token_uses_form_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            captured["url"] = url
            captured.update(kwargs)
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    provider = YouTubeProvider(
        Settings(
            _env_file=None,
            google_oauth_client_id="fake-client",
            google_oauth_client_secret="fake-secret",
            google_oauth_redirect_uri="http://127.0.0.1:8000/callback",
            youtube_request_timeout=1,
        )
    )
    asyncio.run(provider.revoke_token("fake-revoke-token"))

    assert captured["url"] == "https://oauth2.googleapis.com/revoke"
    assert captured["data"] == {"token": "fake-revoke-token"}
    assert "params" not in captured


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ConnectTimeout])
def test_token_connect_error_retries_once_then_succeeds(
    error_type: type[httpx.RequestError],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = httpx.Request("POST", "https://oauth2.googleapis.test/token")
    ScriptedAsyncClient.reset(
        posts=[
            error_type("safe connect failure", request=request),
            httpx.Response(
                200,
                request=request,
                json={"access_token": "safe-fake-access", "expires_in": 3600},
            ),
        ]
    )
    monkeypatch.setattr(httpx, "AsyncClient", ScriptedAsyncClient)

    tokens = asyncio.run(
        YouTubeProvider(enabled_settings(tmp_path)).refresh_access_token(
            "safe-fake-refresh"
        )
    )

    assert tokens.access_token == "safe-fake-access"
    assert ScriptedAsyncClient.post_calls == 2


def test_upload_session_connect_error_retries_once_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "safe-fake-video.mp4"
    path.write_bytes(b"safe-fake-video")
    request = httpx.Request("POST", "https://www.googleapis.test/upload")
    ScriptedAsyncClient.reset(
        posts=[
            httpx.ConnectError("safe connect failure", request=request),
            httpx.Response(
                200,
                request=request,
                headers={"location": "https://upload.example/safe-session"},
            ),
        ],
        puts=[httpx.Response(200, request=request, json={"id": "safe-video-id"})],
    )
    monkeypatch.setattr(httpx, "AsyncClient", ScriptedAsyncClient)

    result = asyncio.run(
        YouTubeProvider(enabled_settings(tmp_path)).upload_video(
            access_token="safe-fake-access",
            path=path,
            content_type="video/mp4",
            title="Safe title",
            description="Safe description",
            tags=["SafeTag"],
            made_for_kids=False,
        )
    )

    assert result.video_id == "safe-video-id"
    assert ScriptedAsyncClient.post_calls == 2
    assert ScriptedAsyncClient.put_calls == 1


def test_two_upload_session_connect_errors_create_one_failed_task(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_provider = FakeYouTubeProvider()
    settings, storage = configure(tmp_path, fake_provider)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    account = connect_account(client, db_session, product_id)
    payload = metadata(account.id, artifact_id)
    preflight = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube/preflight", json=payload
    ).json()
    request = httpx.Request("POST", "https://www.googleapis.test/upload")
    ScriptedAsyncClient.reset(
        posts=[
            httpx.ConnectError("first safe connect failure", request=request),
            httpx.ConnectError("second safe connect failure", request=request),
        ]
    )
    monkeypatch.setattr(httpx, "AsyncClient", ScriptedAsyncClient)
    app.dependency_overrides[get_youtube_provider] = lambda: YouTubeProvider(settings)

    published = client.post(
        f"/api/v1/products/{product_id}/publishing/youtube",
        json=publish_request(payload, preflight),
    )
    assert published.status_code == 201
    assert ScriptedAsyncClient.post_calls == 0
    assert (
        run_youtube_worker(
            db_session,
            settings,
            storage,
            YouTubeProvider(settings),
            "youtube-session-connect-errors",
        ).status
        == WorkerRunStatus.FAILED
    )
    task = db_session.scalar(select(PublishTask))

    assert task is not None
    assert task.status == "FAILED"
    assert task.uncertain is False
    assert task.safe_error_code == "upload_session_connection_failed"
    assert ScriptedAsyncClient.post_calls == 2
    assert ScriptedAsyncClient.put_calls == 0
    assert db_session.scalar(select(func.count()).select_from(PublishTask)) == 1


@pytest.mark.parametrize(
    "error_type",
    [httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError],
)
def test_upload_session_response_transport_errors_do_not_retry(
    error_type: type[httpx.RequestError],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "safe-fake-video.mp4"
    path.write_bytes(b"safe-fake-video")
    request = httpx.Request("POST", "https://www.googleapis.test/upload")
    ScriptedAsyncClient.reset(
        posts=[error_type("safe response failure", request=request)]
    )
    monkeypatch.setattr(httpx, "AsyncClient", ScriptedAsyncClient)

    with pytest.raises(YouTubeProviderError) as raised:
        asyncio.run(
            YouTubeProvider(enabled_settings(tmp_path)).upload_video(
                access_token="safe-fake-access",
                path=path,
                content_type="video/mp4",
                title="Safe title",
                description="Safe description",
                tags=["SafeTag"],
                made_for_kids=False,
            )
        )

    assert raised.value.safe_error_code == "upload_session_response_failed"
    assert raised.value.uncertain is False
    assert ScriptedAsyncClient.post_calls == 1
    assert ScriptedAsyncClient.put_calls == 0


@pytest.mark.parametrize("status", [400, 500])
def test_upload_session_http_errors_do_not_retry(
    status: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "safe-fake-video.mp4"
    path.write_bytes(b"safe-fake-video")
    request = httpx.Request("POST", "https://www.googleapis.test/upload")
    ScriptedAsyncClient.reset(posts=[httpx.Response(status, request=request)])
    monkeypatch.setattr(httpx, "AsyncClient", ScriptedAsyncClient)

    with pytest.raises(YouTubeProviderError):
        asyncio.run(
            YouTubeProvider(enabled_settings(tmp_path)).upload_video(
                access_token="safe-fake-access",
                path=path,
                content_type="video/mp4",
                title="Safe title",
                description="Safe description",
                tags=["SafeTag"],
                made_for_kids=False,
            )
        )

    assert ScriptedAsyncClient.post_calls == 1
    assert ScriptedAsyncClient.put_calls == 0


def test_media_timeout_is_uncertain_and_never_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "safe-fake-video.mp4"
    path.write_bytes(b"safe-fake-video")
    request = httpx.Request("POST", "https://www.googleapis.test/upload")
    ScriptedAsyncClient.reset(
        posts=[
            httpx.Response(
                200,
                request=request,
                headers={"location": "https://upload.example/safe-session"},
            )
        ],
        puts=[httpx.WriteTimeout("safe media timeout", request=request)],
    )
    monkeypatch.setattr(httpx, "AsyncClient", ScriptedAsyncClient)

    with pytest.raises(YouTubeUploadUncertain) as raised:
        asyncio.run(
            YouTubeProvider(enabled_settings(tmp_path)).upload_video(
                access_token="safe-fake-access",
                path=path,
                content_type="video/mp4",
                title="Safe title",
                description="Safe description",
                tags=["SafeTag"],
                made_for_kids=False,
            )
        )

    assert raised.value.safe_error_code == "upload_media_result_uncertain"
    assert raised.value.uncertain is True
    assert ScriptedAsyncClient.post_calls == 1
    assert ScriptedAsyncClient.put_calls == 1
