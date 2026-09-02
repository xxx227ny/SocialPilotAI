from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import SocialAccount

PASSWORD = "strong-user-password"


def settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_user_auth=True,
        allow_public_registration=True,
        user_auth_session_ttl_seconds=3600,
        user_credential_encryption_key=Fernet.generate_key().decode("ascii"),
    )


def register(client: TestClient, email: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()


def create_product(client: TestClient, name: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/products",
        json={
            "name": name,
            "category": "Consumer Electronics",
            "description": "A product description long enough for validation.",
            "selling_points": ["Portable design"],
            "target_markets": ["USA"],
        },
    )
    assert response.status_code == 201
    return response.json()


def seed_account(
    db: Session,
    *,
    workspace_id: int,
    product_id: int,
    platform: str,
    identity: str,
) -> SocialAccount:
    account = SocialAccount(
        workspace_id=workspace_id,
        product_id=product_id,
        platform=platform,
        provider_account_id=identity,
        display_name=f"{identity} display",
        scopes=["publish"],
        access_token_ciphertext=f"secret-access-{identity}",
        refresh_token_ciphertext=f"secret-refresh-{identity}",
        connection_status="CONNECTED",
        encryption_key_id="test-key",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def test_social_account_overview_is_workspace_private_and_never_returns_tokens(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = settings
    first = register(client, "social-first@example.com")
    first_product = create_product(client, "First Workspace Product")
    first_account = seed_account(
        db_session,
        workspace_id=int(first["workspace_id"]),
        product_id=int(first_product["id"]),
        platform="youtube",
        identity="first-channel",
    )
    client.post("/api/v1/auth/logout")

    second = register(client, "social-second@example.com")
    second_product = create_product(client, "Second Workspace Product")
    second_account = seed_account(
        db_session,
        workspace_id=int(second["workspace_id"]),
        product_id=int(second_product["id"]),
        platform="instagram",
        identity="second-professional-account",
    )

    overview = client.get("/api/v1/social-accounts/overview")

    assert overview.status_code == 200
    assert overview.json() == [
        {
            "id": second_account.id,
            "product_id": second_product["id"],
            "platform": "instagram",
            "provider_account_id": "second-professional-account",
            "display_name": "second-professional-account display",
            "scopes": ["publish"],
            "connection_status": "CONNECTED",
            "token_expires_at": None,
            "refresh_token_expires_at": None,
            "created_at": second_account.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": second_account.updated_at.isoformat().replace("+00:00", "Z"),
            "disconnected_at": None,
            "product_name": "Second Workspace Product",
        }
    ]
    serialized = overview.text
    assert "secret-access" not in serialized
    assert "secret-refresh" not in serialized
    assert first_account.provider_account_id not in serialized

    foreign_disconnect = client.post(
        f"/api/v1/social-accounts/{first_account.id}/local-disconnect",
        json={"confirm_disconnect": True},
    )
    assert foreign_disconnect.status_code == 404


def test_local_disconnect_clears_tokens_without_provider_configuration(
    client: TestClient,
    db_session: Session,
) -> None:
    app.dependency_overrides[get_settings] = settings
    principal = register(client, "disconnect@example.com")
    product = create_product(client, "Disconnect Product")
    account = seed_account(
        db_session,
        workspace_id=int(principal["workspace_id"]),
        product_id=int(product["id"]),
        platform="tiktok",
        identity="creator-123",
    )

    response = client.post(
        f"/api/v1/social-accounts/{account.id}/local-disconnect",
        json={"confirm_disconnect": True},
    )
    db_session.refresh(account)

    assert response.status_code == 200
    assert response.json()["local_only"] is True
    assert response.json()["provider_authorization_revoked"] is False
    assert response.json()["account"]["product_name"] == "Disconnect Product"
    assert response.json()["account"]["connection_status"] == "DISCONNECTED"
    assert account.access_token_ciphertext is None
    assert account.refresh_token_ciphertext is None
    assert account.connection_status == "DISCONNECTED"
    assert account.disconnected_at is not None

