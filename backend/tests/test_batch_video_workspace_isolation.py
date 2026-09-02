from decimal import Decimal

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app
from app.models import BatchVideoVariant, MarketingStrategy, ProductAsset


def user_settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_user_auth=True,
        allow_public_registration=True,
        user_auth_cookie_secure=False,
        user_credential_encryption_key=Fernet.generate_key().decode("ascii"),
        enable_qwen_video_script_generation=True,
        qwen_video_script_cost_min=Decimal("0.02"),
        qwen_video_script_cost_max=Decimal("0.08"),
        qwen_video_script_cost_basis="workspace-isolation-test",
    )


def register(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "strong-workspace-password"},
    )
    assert response.status_code == 201


def create_product(client: TestClient, name: str) -> int:
    response = client.post(
        "/api/v1/products",
        json={
            "name": name,
            "category": "Workspace isolation",
            "description": "A product used to verify batch workspace boundaries.",
            "selling_points": ["Private workspace"],
            "target_markets": ["US"],
        },
    )
    assert response.status_code == 201
    return int(response.json()["id"])


def create_batch(
    client: TestClient,
    product_id: int,
    platforms: list[str] | None = None,
) -> tuple[int, int]:
    request = {
        "product_ids": [product_id],
        "platforms": platforms or ["youtube"],
        "variants_per_platform": 1,
        "duration_seconds": 15,
        "aspect_ratio": "9:16",
        "language": "en-US",
        "priority": 50,
        "max_concurrency": 1,
        "creative_angle": None,
        "idempotency_key": f"workspace-batch-{product_id}",
    }
    checked = client.post("/api/v1/batch-video-jobs/preflight", json=request)
    assert checked.status_code == 200
    preflight = checked.json()
    created = client.post(
        "/api/v1/batch-video-jobs",
        json={
            **request,
            "request_digest": preflight["request_digest"],
            "preflight_digest": preflight["preflight_digest"],
            "preflight_expires_at": preflight["expires_at"],
            "cost_confirmed": True,
        },
    )
    assert created.status_code == 201
    body = created.json()
    return int(body["batch"]["id"]), int(body["variants"][0]["id"])


def test_batch_and_variant_exact_ids_are_private_to_owning_workspace(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = user_settings
    register(client, "batch-owner-a@example.com")
    product_id = create_product(client, "Private batch product")
    batch_id, variant_id = create_batch(client, product_id)
    assert client.post("/api/v1/auth/logout").status_code == 200

    register(client, "batch-owner-b@example.com")

    for method, path in (
        ("get", f"/api/v1/batch-video-jobs/{batch_id}"),
        ("get", f"/api/v1/batch-video-jobs/{batch_id}/variants"),
        ("get", f"/api/v1/batch-video-variants/{variant_id}"),
        ("post", f"/api/v1/batch-video-jobs/{batch_id}/pause"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 404
        assert str(batch_id) not in response.text
        assert str(variant_id) not in response.text

    cross_product_preflight = client.post(
        "/api/v1/batch-video-jobs/preflight",
        json={
            "product_ids": [product_id],
            "platforms": ["youtube"],
            "variants_per_platform": 1,
            "duration_seconds": 15,
            "aspect_ratio": "9:16",
            "language": "en-US",
            "priority": 50,
            "max_concurrency": 1,
            "creative_angle": None,
            "idempotency_key": "cross-workspace-preflight",
        },
    )
    assert cross_product_preflight.status_code == 404

    script_versions = client.get(
        f"/api/v1/batch-video-variants/{variant_id}/script-versions"
    )
    assert script_versions.status_code == 404

    qwen_preflight = client.post(
        f"/api/v1/batch-video-variants/{variant_id}/qwen-script/preflight",
        json={
            "idempotency_key": "cross-workspace-qwen",
            "strategy_id": 1,
            "copy_matrix_id": None,
            "parent_version_id": None,
        },
    )
    assert qwen_preflight.status_code == 404


def test_video_workflow_context_selects_owned_latest_sources_and_stays_private(
    client: TestClient, db_session
) -> None:
    app.dependency_overrides[get_settings] = user_settings
    register(client, "workflow-owner-a@example.com")
    product_id = create_product(client, "Workflow context product")
    batch_id, _ = create_batch(
        client, product_id, ["youtube", "tiktok", "instagram"]
    )
    variants = db_session.query(BatchVideoVariant).filter_by(
        batch_video_job_id=batch_id
    )
    for variant in variants:
        variant.status = "READY_FOR_SCRIPT"
    strategy = MarketingStrategy(
        product_id=product_id,
        positioning="Owned strategy",
        audience_insights=["Owned audience"],
        angles=["Owned angle"],
        risks=["Owned risk"],
        evidence=["Owned product record"],
    )
    asset = ProductAsset(
        product_id=product_id,
        file_name="owned-product.webp",
        file_path="products/owned-product.webp",
        file_type="image",
        content_type="image/webp",
        size_bytes=128,
        sha256="a" * 64,
        storage_identity="owned-product-image",
    )
    db_session.add_all([strategy, asset])
    db_session.commit()

    response = client.get(
        f"/api/v1/products/{product_id}/video-workflow-context"
    )
    assert response.status_code == 200
    assert response.json() == {
        "product_id": product_id,
        "batch_id": batch_id,
        "strategy_id": strategy.id,
        "copy_matrix_id": None,
        "reference_asset_id": asset.id,
        "ready": True,
        "missing_requirements": [],
    }

    assert client.post("/api/v1/auth/logout").status_code == 200
    register(client, "workflow-owner-b@example.com")
    denied = client.get(
        f"/api/v1/products/{product_id}/video-workflow-context"
    )
    assert denied.status_code == 404
