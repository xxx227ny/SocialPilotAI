import ctypes
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_text_generation_provider,
    get_visual_generation_provider,
    get_youtube_provider,
)
from app.core.config import Settings, get_settings
from app.main import app
from app.models import Product
from app.services import system_readiness_service as readiness_module
from app.services.database_migration_service import HEAD_REVISION


def mark_database_at_head(session: Session) -> None:
    session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    session.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
        {"revision": HEAD_REVISION},
    )
    session.commit()


def ready_settings(artifact_root: str) -> Settings:
    worker_status = Path(artifact_root) / "worker-status.json"
    worker_status.write_text(
        json.dumps(
            {
                "version": 1,
                "state": "healthy",
                "pid": os.getpid(),
                "updated_at_utc": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    return Settings(
        _env_file=None,
        qwen_api_key="fake-qwen-readiness-key",
        wanx_api_key="fake-wanx-readiness-key",
        wanx_endpoint="https://safe-workspace.cn-beijing.maas.aliyuncs.com/api/v1",
        google_oauth_client_id="fake-google-client-id",
        google_oauth_client_secret="fake-google-client-secret",
        google_oauth_redirect_uri=(
            "http://127.0.0.1:8000/api/v1/social-accounts/youtube/callback"
        ),
        instagram_app_id="fake-instagram-app-id",
        instagram_app_secret="fake-instagram-app-secret",
        instagram_oauth_redirect_uri=(
            "http://127.0.0.1:8000/api/v1/social-accounts/instagram/callback"
        ),
        instagram_graph_api_version="v23.0",
        tiktok_client_key="fake-tiktok-client-key",
        tiktok_client_secret="fake-tiktok-client-secret",
        tiktok_oauth_redirect_uri=(
            "https://app.example/api/v1/social-accounts/tiktok/callback"
        ),
        pinterest_client_id="fake-pinterest-client-id",
        pinterest_client_secret="fake-pinterest-client-secret",
        pinterest_oauth_redirect_uri=(
            "https://app.example/api/v1/social-accounts/pinterest/callback"
        ),
        social_token_encryption_key=Fernet.generate_key().decode("ascii"),
        video_artifact_storage_root=artifact_root,
        execution_worker_status_file=str(worker_status),
        enable_strategy_execution=True,
        enable_copy_execution=True,
        enable_video_project_execution=True,
        enable_video_render_execution=True,
        enable_social_account_binding=True,
        enable_youtube_publishing=True,
        enable_instagram_account_binding=True,
        enable_tiktok_account_binding=True,
        enable_pinterest_account_binding=True,
    )


def test_readiness_is_provider_free_read_only_and_secret_safe(
    client: TestClient,
    db_session: Session,
    tmp_path,
) -> None:
    settings = ready_settings(str(tmp_path))
    provider_resolutions = 0

    def forbidden_provider():
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Readiness must not resolve a Provider")

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    app.dependency_overrides[get_visual_generation_provider] = forbidden_provider
    app.dependency_overrides[get_youtube_provider] = forbidden_provider
    mark_database_at_head(db_session)
    before = db_session.scalar(select(func.count(Product.id)))

    response = client.get("/api/v1/system/readiness")

    after = db_session.scalar(select(func.count(Product.id)))
    assert response.status_code == 200
    body = response.json()
    assert all(
        body[key]["ready"] is True
        for key in (
            "backend",
            "qwen",
            "wanx",
            "google_youtube",
            "meta_instagram",
            "tiktok",
            "pinterest",
            "database",
            "artifact_storage",
            "execution_worker",
        )
    )
    assert body["provider_calls"] == 0
    assert body["database_writes"] == 0
    assert body["automatic_actions"] is False
    assert provider_resolutions == 0
    assert before == after == 0
    assert body["database"]["revision_status"] == "head"
    assert body["database"]["revision"] == HEAD_REVISION
    serialized = json.dumps(body)
    for secret in (
        "fake-qwen-readiness-key",
        "fake-wanx-readiness-key",
        "fake-google-client-id",
        "fake-google-client-secret",
        "fake-instagram-app-id",
        "fake-instagram-app-secret",
        "fake-tiktok-client-key",
        "fake-tiktok-client-secret",
        "fake-pinterest-client-id",
        "fake-pinterest-client-secret",
        settings.social_token_encryption_key.get_secret_value(),
    ):
        assert secret not in serialized


def test_readiness_explains_missing_local_configuration(
    client: TestClient,
    db_session: Session,
    tmp_path,
) -> None:
    missing_artifacts = tmp_path / "missing-artifacts"
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        video_artifact_storage_root=str(missing_artifacts),
        enable_strategy_execution=True,
        enable_copy_execution=True,
        enable_video_project_execution=True,
        enable_video_render_execution=True,
        enable_social_account_binding=True,
        enable_youtube_publishing=True,
    )
    mark_database_at_head(db_session)

    response = client.get("/api/v1/system/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["backend"]["ready"] is True
    assert body["database"]["ready"] is True
    assert body["qwen"]["ready"] is False
    assert "QWEN_API_KEY" in body["qwen"]["message"]
    assert body["wanx"]["ready"] is False
    assert "WANX_API_KEY" in body["wanx"]["message"]
    assert body["google_youtube"]["ready"] is False
    assert body["meta_instagram"]["ready"] is False
    assert body["tiktok"]["ready"] is False
    assert body["pinterest"]["ready"] is False
    assert body["artifact_storage"]["ready"] is False
    assert body["execution_worker"]["ready"] is False
    assert body["execution_worker"]["status"] == "not_running"


def test_readiness_reports_unversioned_database_without_path_or_write(
    client: TestClient,
    db_session: Session,
    tmp_path,
) -> None:
    app.dependency_overrides[get_settings] = lambda: ready_settings(str(tmp_path))
    before = db_session.scalar(select(func.count(Product.id)))

    response = client.get("/api/v1/system/readiness")

    after = db_session.scalar(select(func.count(Product.id)))
    assert response.status_code == 200
    database = response.json()["database"]
    assert database["ready"] is False
    assert database["revision_status"] == "upgrade_required"
    assert database["revision"] is None
    assert "Runtime" not in database["message"]
    assert before == after == 0


def test_readiness_reports_stale_worker_without_exposing_identity(
    client: TestClient,
    db_session: Session,
    tmp_path,
) -> None:
    settings = ready_settings(str(tmp_path))
    worker_status = Path(settings.execution_worker_status_file or "")
    worker_status.write_text(
        json.dumps(
            {
                "state": "healthy",
                "pid": 98765,
                "worker_path": "must-not-leak",
                "updated_at_utc": (
                    datetime.now(UTC) - timedelta(minutes=2)
                ).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    mark_database_at_head(db_session)

    response = client.get("/api/v1/system/readiness")

    assert response.status_code == 200
    worker = response.json()["execution_worker"]
    assert worker == {
        "ready": False,
        "message": "Execution Worker heartbeat is stale; restart SocialPilotAI safely.",
        "status": "stale",
    }
    serialized = json.dumps(response.json())
    assert "98765" not in serialized
    assert "must-not-leak" not in serialized


class FakeWin32Function:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


def test_windows_process_check_uses_open_process_and_closes_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[int] = []

    def get_exit_code(_handle, exit_code) -> int:
        exit_code._obj.value = 259
        return 1

    kernel32 = SimpleNamespace(
        OpenProcess=FakeWin32Function(lambda *_args: 41),
        GetExitCodeProcess=FakeWin32Function(get_exit_code),
        CloseHandle=FakeWin32Function(lambda handle: closed.append(handle) or 1),
    )
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False
    )

    assert readiness_module._windows_process_state(1234) == "running"
    assert closed == [41]


def test_windows_process_branch_never_calls_os_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(readiness_module.sys, "platform", "win32")
    monkeypatch.setattr(
        readiness_module, "_windows_process_state", lambda _pid: "running"
    )
    monkeypatch.setattr(
        readiness_module.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(AssertionError("os.kill called")),
    )

    assert readiness_module._process_state(1234) == "running"


@pytest.mark.parametrize(
    ("process_state", "message_fragment"),
    [
        ("missing", "is not running"),
        ("unknown", "could not be safely confirmed"),
    ],
)
def test_readiness_safely_reports_missing_or_unconfirmed_windows_worker(
    client: TestClient,
    db_session: Session,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    process_state: str,
    message_fragment: str,
) -> None:
    settings = ready_settings(str(tmp_path))
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(readiness_module, "_process_state", lambda _pid: process_state)
    mark_database_at_head(db_session)

    response = client.get("/api/v1/system/readiness")

    assert response.status_code == 200
    worker = response.json()["execution_worker"]
    assert worker["ready"] is False
    assert worker["status"] == "not_running"
    assert message_fragment in worker["message"]
