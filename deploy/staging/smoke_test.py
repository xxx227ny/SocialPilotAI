"""Non-billable deployed staging smoke test with two isolated users."""

import argparse
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

import httpx


def require_status(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url.path} returned "
            f"{response.status_code}, expected {expected}"
        )


def seed_validation_account(database: Path, email: str, password: str, name: str):
    """Local-only fixture: no SMTP and no changes to real user verification."""
    if not re.fullmatch(
        r"(?:smoke-[ab]|media-(?:owner|other))-[0-9]{14}[0-9a-f]{6}@invalid\.example",
        email,
    ):
        raise ValueError("Only generated smoke identities may be seeded")
    if not database.is_file():
        raise ValueError("Fixture database must already exist")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import User
    from app.services.user_auth_service import register_user

    engine = create_engine(f"sqlite:///{database.resolve().as_posix()}")
    try:
        with Session(engine) as session:
            principal, _ = register_user(
                session,
                email=email,
                password=password,
                workspace_name=name,
                session_ttl_seconds=3600,
            )
            session.get(User, principal.user_id).email_verified_at = datetime.now(UTC)
            session.commit()
    finally:
        engine.dispose()


def register(
    client: httpx.Client,
    email: str,
    password: str,
    name: str,
    fixture_database: Path | None = None,
) -> dict:
    if fixture_database is not None:
        seed_validation_account(fixture_database, email, password, name)
        response = client.post(
            "/api/v1/auth/login", json={"username": email, "password": password}
        )
        require_status(response, 200)
    else:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "workspace_name": name},
        )
        require_status(response, 201)
    cookie = response.headers.get("set-cookie", "")
    if (
        "HttpOnly" not in cookie
        or "Secure" not in cookie
        or "SameSite=lax" not in cookie
    ):
        raise RuntimeError("Registration did not return the required secure cookie")
    return response.json()


def save_key(
    client: httpx.Client,
    api_key: str,
    *,
    provider_workspace_id: str | None = None,
) -> dict:
    response = client.put(
        "/api/v1/credentials/dashscope",
        json={
            "api_key": api_key,
            "region": "cn-beijing",
            "provider_workspace_id": provider_workspace_id,
        },
    )
    require_status(response, 200)
    if api_key in response.text:
        raise RuntimeError("Credential response exposed the API key")
    result = response.json()
    if result.get("region") != "cn-beijing":
        raise RuntimeError("Credential region was not preserved")
    if result.get("provider_workspace_id") != provider_workspace_id:
        raise RuntimeError("Credential workspace profile was not preserved")
    return result


def reject_arbitrary_provider_host(client: httpx.Client, api_key: str) -> None:
    response = client.put(
        "/api/v1/credentials/dashscope",
        json={
            "api_key": api_key,
            "region": "cn-beijing",
            "provider_workspace_id": "https://attacker.invalid/path",
        },
    )
    require_status(response, 422)
    if api_key in response.text:
        raise RuntimeError("Rejected credential response exposed the API key")


def verify_invalid_key(client: httpx.Client, api_key: str) -> dict:
    response = client.post("/api/v1/credentials/dashscope/verify")
    require_status(response, 200)
    if api_key in response.text:
        raise RuntimeError("Credential verification response exposed the API key")
    result = response.json()
    if result.get("status") != "INVALID" or result.get("verified") is not False:
        raise RuntimeError("Synthetic API key was not rejected safely")
    return result


def create_product(client: httpx.Client, name: str, request_key: str) -> dict:
    request = {
        "headers": {"Idempotency-Key": request_key},
        "json": {
            "name": name,
            "category": "Deployment Validation",
            "description": (
                "A non-billable product used for staging isolation validation."
            ),
            "selling_points": ["Workspace isolated"],
            "target_markets": ["Validation only"],
        },
    }
    response = client.post(
        "/api/v1/products",
        **request,
    )
    require_status(response, 201)
    repeated = client.post("/api/v1/products", **request)
    require_status(repeated, 201)
    if repeated.json().get("id") != response.json().get("id"):
        raise RuntimeError("Repeated product request created a duplicate")
    return repeated.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument(
        "--fixture-database",
        type=Path,
        help="Local synthetic verified users; does not test SMTP",
    )
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
        landing = first.get("/")
        require_status(landing, 200)
        if "text/html" not in landing.headers.get("content-type", ""):
            raise RuntimeError("Staging root did not return the product frontend")
        if '<div id="root"></div>' not in landing.text:
            raise RuntimeError("Staging root returned an unexpected HTML document")

        session = first.get("/api/v1/auth/session")
        require_status(session, 200)
        anonymous = session.json()
        if (
            anonymous.get("enabled") is not True
            or anonymous.get("authenticated") is not False
            or anonymous.get("auth_mode") != "user"
            or anonymous.get("registration_enabled") is not True
            or not isinstance(anonymous.get("email_delivery_available"), bool)
            or not isinstance(anonymous.get("email_verification_required"), bool)
        ):
            raise RuntimeError("Unexpected anonymous session state")
        if anonymous["email_verification_required"] and not arguments.fixture_database:
            raise RuntimeError(
                "Verified-email policy requires local --fixture-database"
            )

        account_a = register(
            first,
            f"smoke-a-{run_id}@invalid.example",
            password_a,
            "Smoke Workspace A",
            arguments.fixture_database,
        )
        account_b = register(
            second,
            f"smoke-b-{run_id}@invalid.example",
            password_b,
            "Smoke Workspace B",
            arguments.fixture_database,
        )
        if account_a["workspace_id"] == account_b["workspace_id"]:
            raise RuntimeError("The two users received the same workspace")

        reject_arbitrary_provider_host(first, key_a)
        credential_a = save_key(first, key_a)
        credential_b = save_key(
            second,
            key_b,
            provider_workspace_id="smoke-workspace-b",
        )
        if credential_a["key_hint"] == credential_b["key_hint"]:
            raise RuntimeError("Credential hints did not remain user-specific")
        verify_invalid_key(first, key_a)

        product_a = create_product(
            first,
            "Smoke Product A " + run_id,
            "smoke-product-create-" + run_id,
        )
        if second.get("/api/v1/products").json() != []:
            raise RuntimeError("Second workspace can see first workspace products")
        require_status(second.get(f"/api/v1/products/{product_a['id']}"), 404)

        product_b = create_product(
            second,
            "Smoke Product B " + run_id,
            "smoke-product-create-" + run_id,
        )
        first_products = first.get("/api/v1/products")
        require_status(first_products, 200)
        if [item["id"] for item in first_products.json()] != [product_a["id"]]:
            raise RuntimeError("First workspace product list is not isolated")
        require_status(first.get(f"/api/v1/products/{product_b['id']}"), 404)

        first_summary = first.get("/api/v1/dashboard/workspace-summary")
        second_summary = second.get("/api/v1/dashboard/workspace-summary")
        require_status(first_summary, 200)
        require_status(second_summary, 200)
        for summary in (first_summary.json(), second_summary.json()):
            if summary.get("data_scope") != "current_workspace":
                raise RuntimeError("Workspace summary did not declare its data scope")
            if summary.get("ai_calls") != 0:
                raise RuntimeError("Workspace summary unexpectedly reported an AI call")
            if summary.get("ai_job_count") != 0:
                raise RuntimeError("Workspace summary unexpectedly reported an AI job")
            if summary.get("connected_social_account_count") != 0:
                raise RuntimeError("Workspace summary leaked a social connection")
            if summary.get("publish_task_count") != 0:
                raise RuntimeError("Workspace summary leaked a publish task")
            if summary.get("product_count") != 1:
                raise RuntimeError("Workspace summary leaked or omitted a product")
        if first_summary.json().get("api_key_configured") is not True:
            raise RuntimeError("First workspace credential was not counted")
        if second_summary.json().get("api_key_configured") is not True:
            raise RuntimeError("Second workspace credential was not counted")

        require_status(first.post("/api/v1/auth/logout"), 200)
        require_status(second.post("/api/v1/auth/logout"), 200)
        require_status(first.get("/api/v1/products"), 401)
        require_status(second.get("/api/v1/products"), 401)

    print("Staging smoke passed: auth, secure cookies, credentials, and isolation")


if __name__ == "__main__":
    main()
