from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.credentials import get_dashscope_credential_verifier
from app.core.config import Settings, get_settings
from app.main import app
from app.models import ProviderCredential
from app.services.provider_credential_service import (
    CredentialCipher,
    ProviderCredentialService,
)
from app.services.provider_credential_verifier import CredentialVerificationResult

PASSWORD = "strong-user-password"
API_KEY = "sk-user-owned-dashscope-key-123456"


class SuccessfulVerifier:
    def verify(self, api_key: str) -> CredentialVerificationResult:
        assert api_key == API_KEY
        return CredentialVerificationResult(
            status="VERIFIED",
            verified=True,
            message="API Key 验证通过。",
        )


class InvalidVerifier:
    def verify(self, api_key: str) -> CredentialVerificationResult:
        assert api_key == API_KEY
        return CredentialVerificationResult(
            status="INVALID",
            verified=False,
            message="API Key 无效。",
        )


def credential_settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_user_auth=True,
        allow_public_registration=True,
        user_auth_session_ttl_seconds=3600,
        user_auth_cookie_secure=False,
        user_credential_encryption_key=Fernet.generate_key().decode("ascii"),
        user_credential_encryption_key_id="test-v1",
    )


def register(client: TestClient, email: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()


def test_user_can_bind_read_and_delete_encrypted_dashscope_key(
    client: TestClient,
    db_session: Session,
) -> None:
    settings = credential_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    account = register(client, "owner@example.com")

    empty = client.get("/api/v1/credentials/dashscope")
    saved = client.put(
        "/api/v1/credentials/dashscope",
        json={"api_key": API_KEY},
    )
    visible = client.get("/api/v1/credentials/dashscope")

    assert empty.status_code == 200
    assert empty.json() == {
        "provider": "DASHSCOPE",
        "configured": False,
        "key_hint": None,
        "verified": False,
        "verified_at": None,
        "updated_at": None,
    }
    assert saved.status_code == 200
    assert saved.json()["configured"] is True
    assert saved.json()["key_hint"] == "••••3456"
    assert API_KEY not in saved.text
    assert visible.status_code == 200
    assert visible.json()["key_hint"] == "••••3456"
    assert API_KEY not in visible.text

    stored = db_session.scalar(select(ProviderCredential))
    assert stored is not None
    assert stored.workspace_id == account["workspace_id"]
    assert stored.secret_ciphertext != API_KEY
    assert API_KEY not in stored.secret_ciphertext
    assert stored.encryption_key_id == "test-v1"
    assert CredentialCipher(settings).decrypt(stored.secret_ciphertext) == API_KEY
    assert (
        ProviderCredentialService(db_session, settings).read_verified_dashscope_key(
            account["workspace_id"]
        )
        is None
    )

    deleted = client.delete("/api/v1/credentials/dashscope")
    after_delete = client.get("/api/v1/credentials/dashscope")
    assert deleted.status_code == 204
    assert after_delete.json()["configured"] is False
    assert db_session.scalar(select(ProviderCredential)) is None


def test_saved_key_must_verify_before_ai_use(
    client: TestClient,
    db_session: Session,
) -> None:
    settings = credential_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_dashscope_credential_verifier] = lambda: (
        SuccessfulVerifier()
    )
    account = register(client, "verified@example.com")
    assert (
        client.put(
            "/api/v1/credentials/dashscope", json={"api_key": API_KEY}
        ).status_code
        == 200
    )

    verified = client.post("/api/v1/credentials/dashscope/verify")
    visible = client.get("/api/v1/credentials/dashscope")

    assert verified.status_code == 200
    assert verified.json()["status"] == "VERIFIED"
    assert verified.json()["verified"] is True
    assert verified.json()["verified_at"] is not None
    assert API_KEY not in verified.text
    assert visible.json()["verified"] is True
    assert visible.json()["verified_at"] is not None
    assert (
        ProviderCredentialService(db_session, settings).read_verified_dashscope_key(
            account["workspace_id"]
        )
        == API_KEY
    )


def test_invalid_key_stays_encrypted_but_cannot_be_used(
    client: TestClient,
    db_session: Session,
) -> None:
    settings = credential_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_dashscope_credential_verifier] = lambda: (
        InvalidVerifier()
    )
    account = register(client, "invalid@example.com")
    assert (
        client.put(
            "/api/v1/credentials/dashscope", json={"api_key": API_KEY}
        ).status_code
        == 200
    )

    invalid = client.post("/api/v1/credentials/dashscope/verify")

    assert invalid.status_code == 200
    assert invalid.json()["status"] == "INVALID"
    assert invalid.json()["verified"] is False
    assert API_KEY not in invalid.text
    assert (
        ProviderCredentialService(db_session, settings).read_dashscope_key(
            account["workspace_id"]
        )
        == API_KEY
    )
    assert (
        ProviderCredentialService(db_session, settings).read_verified_dashscope_key(
            account["workspace_id"]
        )
        is None
    )


def test_verification_requires_a_saved_key(client: TestClient) -> None:
    settings = credential_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    register(client, "missing@example.com")

    response = client.post("/api/v1/credentials/dashscope/verify")

    assert response.status_code == 409
    assert response.json()["detail"] == "请先保存 API Key，再进行验证。"


def test_provider_credentials_are_isolated_by_workspace(
    client: TestClient,
    db_session: Session,
) -> None:
    settings = credential_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    first = register(client, "first@example.com")
    assert (
        client.put(
            "/api/v1/credentials/dashscope",
            json={"api_key": API_KEY},
        ).status_code
        == 200
    )
    client.post("/api/v1/auth/logout")

    second = register(client, "second@example.com")
    second_view = client.get("/api/v1/credentials/dashscope")

    assert first["workspace_id"] != second["workspace_id"]
    assert second_view.status_code == 200
    assert second_view.json()["configured"] is False
    stored = db_session.scalar(select(ProviderCredential))
    assert stored is not None
    assert stored.workspace_id == first["workspace_id"]


def test_credential_routes_require_real_user_auth(
    client: TestClient,
) -> None:
    settings = credential_settings()
    app.dependency_overrides[get_settings] = lambda: settings

    response = client.get("/api/v1/credentials/dashscope")

    assert response.status_code == 401
    assert API_KEY not in response.text


def test_invalid_credential_is_rejected_without_echoing_secret(
    client: TestClient,
) -> None:
    settings = credential_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    register(client, "owner@example.com")
    invalid_secret = "short-k"

    response = client.put(
        "/api/v1/credentials/dashscope",
        json={"api_key": invalid_secret},
    )

    assert response.status_code == 422
    assert invalid_secret not in response.text
    assert response.json()["detail"] == "API Key 格式无效。"
