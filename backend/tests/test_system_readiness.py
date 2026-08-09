import json

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
from app.services.database_migration_service import HEAD_REVISION


def mark_database_at_head(session: Session) -> None:
    session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    session.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
        {"revision": HEAD_REVISION},
    )
    session.commit()


def ready_settings(artifact_root: str) -> Settings:
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
        social_token_encryption_key=Fernet.generate_key().decode("ascii"),
        video_artifact_storage_root=artifact_root,
        enable_strategy_execution=True,
        enable_copy_execution=True,
        enable_video_project_execution=True,
        enable_video_render_execution=True,
        enable_social_account_binding=True,
        enable_youtube_publishing=True,
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
            "database",
            "artifact_storage",
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
    assert body["artifact_storage"]["ready"] is False


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
