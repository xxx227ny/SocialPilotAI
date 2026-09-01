"""Non-billable deployed staging smoke test with two isolated users."""

import argparse
import secrets
from datetime import UTC, datetime

import httpx


def require_status(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url.path} returned "
            f"{response.status_code}, expected {expected}"
        )


def register(client: httpx.Client, email: str, password: str, name: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "workspace_name": name,
        },
    )
    require_status(response, 201)
    cookie = response.headers.get("set-cookie", "")
    if "HttpOnly" not in cookie or "Secure" not in cookie or "SameSite=lax" not in cookie:
        raise RuntimeError("Registration did not return the required secure cookie")
    return response.json()


def save_key(client: httpx.Client, api_key: str) -> dict:
    response = client.put(
        "/api/v1/credentials/dashscope",
        json={"api_key": api_key},
    )
    require_status(response, 200)
    if api_key in response.text:
        raise RuntimeError("Credential response exposed the API key")
    return response.json()


def create_product(client: httpx.Client, name: str) -> dict:
    response = client.post(
        "/api/v1/products",
        json={
            "name": name,
            "category": "Deployment Validation",
            "description": "A non-billable product used for staging isolation validation.",
            "selling_points": ["Workspace isolated"],
            "target_markets": ["Validation only"],
        },
    )
    require_status(response, 201)
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    arguments = parser.parse_args()
    origin = arguments.origin.rstrip("/")
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    password_a = "Smoke-A-" + secrets.token_urlsafe(18)
    password_b = "Smoke-B-" + secrets.token_urlsafe(18)
    key_a = "sk-smoke-a-" + secrets.token_urlsafe(24)
    key_b = "sk-smoke-b-" + secrets.token_urlsafe(24)
    headers = {"Origin": origin}

    with (
        httpx.Client(
            base_url=origin,
            headers=headers,
            timeout=20,
            trust_env=False,
        ) as first,
        httpx.Client(
            base_url=origin,
            headers=headers,
            timeout=20,
            trust_env=False,
        ) as second,
    ):
        session = first.get("/api/v1/auth/session")
        require_status(session, 200)
        if session.json() != {
            "enabled": True,
            "authenticated": False,
            "auth_mode": "user",
            "registration_enabled": True,
        }:
            raise RuntimeError("Unexpected anonymous session state")

        account_a = register(
            first,
            f"smoke-a-{run_id}@invalid.example",
            password_a,
            "Smoke Workspace A",
        )
        account_b = register(
            second,
            f"smoke-b-{run_id}@invalid.example",
            password_b,
            "Smoke Workspace B",
        )
        if account_a["workspace_id"] == account_b["workspace_id"]:
            raise RuntimeError("The two users received the same workspace")

        credential_a = save_key(first, key_a)
        credential_b = save_key(second, key_b)
        if credential_a["key_hint"] == credential_b["key_hint"]:
            raise RuntimeError("Credential hints did not remain user-specific")

        product_a = create_product(first, "Smoke Product A " + run_id)
        if second.get("/api/v1/products").json() != []:
            raise RuntimeError("Second workspace can see first workspace products")
        require_status(second.get(f"/api/v1/products/{product_a['id']}"), 404)

        product_b = create_product(second, "Smoke Product B " + run_id)
        first_products = first.get("/api/v1/products")
        require_status(first_products, 200)
        if [item["id"] for item in first_products.json()] != [product_a["id"]]:
            raise RuntimeError("First workspace product list is not isolated")
        require_status(first.get(f"/api/v1/products/{product_b['id']}"), 404)

        require_status(first.post("/api/v1/auth/logout"), 200)
        require_status(second.post("/api/v1/auth/logout"), 200)
        require_status(first.get("/api/v1/products"), 401)
        require_status(second.get("/api/v1/products"), 401)

    print("Staging smoke passed: auth, secure cookies, credentials, and isolation")


if __name__ == "__main__":
    main()
