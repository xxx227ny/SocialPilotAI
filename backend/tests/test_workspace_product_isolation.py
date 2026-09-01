from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app

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


def product(name: str) -> dict[str, object]:
    return {
        "name": name,
        "category": "Consumer Electronics",
        "description": "A product description long enough for validation.",
        "selling_points": ["Portable design"],
        "target_markets": ["USA"],
    }


def test_product_records_are_private_to_each_workspace(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = settings
    first_account = register(client, "first@example.com")
    first_product = client.post(
        "/api/v1/products", json=product("First User Product")
    )
    client.post("/api/v1/auth/logout")

    second_account = register(client, "second@example.com")
    second_list_before = client.get("/api/v1/products")
    first_from_second = client.get(
        f"/api/v1/products/{first_product.json()['id']}"
    )
    second_product = client.post(
        "/api/v1/products", json=product("Second User Product")
    )
    second_list_after = client.get("/api/v1/products")

    assert first_product.status_code == 201
    assert first_account["workspace_id"] != second_account["workspace_id"]
    assert second_list_before.json() == []
    assert first_from_second.status_code == 404
    assert second_product.status_code == 201
    assert [item["id"] for item in second_list_after.json()] == [
        second_product.json()["id"]
    ]
