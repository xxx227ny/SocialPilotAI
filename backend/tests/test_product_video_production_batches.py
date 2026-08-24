from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import ProductVideoProductionBatch, ProductVideoProductionItem
from tests.test_three_platform_video_preflight import create_three_platform_sources


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        enable_real_product_video=True,
        enable_happyhorse_product_video=True,
        enable_video_render_execution=True,
        enable_video_composition=True,
        enable_video_composition_enhancement=True,
        qwen_api_key="fake-qwen-key",
        wanx_api_key="fake-wanx-key",
        product_asset_storage_root=str(tmp_path / "images"),
        video_artifact_storage_root=str(tmp_path / "videos"),
        wanx_image_estimated_cost=Decimal("0.10"),
        happyhorse_estimated_cost=Decimal("1.00"),
    )


def test_create_recover_and_control_persistent_three_platform_batch(
    client: TestClient, db_session: Session, tmp_path
) -> None:
    product, asset, selections = create_three_platform_sources(db_session)
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    payload = {
        "reference_product_asset_id": asset.id,
        "reference_product_asset_sha256": asset.sha256,
        "selections": selections,
    }
    checked = client.post(
        f"/api/v1/products/{product.id}/real-product-video/three-platform-preflight",
        json=payload,
    ).json()

    created = client.post(
        f"/api/v1/products/{product.id}/real-product-video/production-batches",
        json={
            **payload,
            "input_digest": checked["input_digest"],
            "idempotency_key": "production-batch-persistent-1",
            "cost_confirmed": True,
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["reused"] is False
    assert body["batch"]["status"] == "WAITING"
    assert Decimal(body["batch"]["known_estimated_cost"]) == Decimal("3.60")
    assert body["batch"]["cost_estimate_complete"] is False
    assert body["batch"]["provider_call_budget"] == 12
    assert [item["platform"] for item in body["items"]] == [
        "tiktok",
        "youtube",
        "instagram",
    ]
    assert {item["stage"] for item in body["items"]} == {"QUEUED"}
    assert {item["status"] for item in body["items"]} == {"WAITING"}
    assert all(
        item["video_project_id"] is None
        and item["final_video_artifact_id"] is None
        and item["subtitle_artifact_id"] is None
        for item in body["items"]
    )

    batch_id = body["batch"]["id"]
    recovered = client.get(
        f"/api/v1/products/{product.id}/real-product-video/production-batches/{batch_id}"
    )
    assert recovered.status_code == 200
    assert recovered.json()["items"] == body["items"]

    reused = client.post(
        f"/api/v1/products/{product.id}/real-product-video/production-batches",
        json={
            **payload,
            "input_digest": checked["input_digest"],
            "idempotency_key": "production-batch-persistent-1",
            "cost_confirmed": True,
        },
    )
    assert reused.status_code == 201
    assert reused.json()["reused"] is True
    assert reused.json()["batch"]["id"] == batch_id
    assert (
        db_session.scalar(select(func.count()).select_from(ProductVideoProductionBatch))
        == 1
    )
    assert (
        db_session.scalar(select(func.count()).select_from(ProductVideoProductionItem))
        == 3
    )

    assert (
        client.post(
            f"/api/v1/products/{product.id}/real-product-video/production-batches/{batch_id}/pause"
        ).json()["batch"]["status"]
        == "PAUSED"
    )
    assert (
        client.post(
            f"/api/v1/products/{product.id}/real-product-video/production-batches/{batch_id}/resume"
        ).json()["batch"]["status"]
        == "WAITING"
    )
    cancelled = client.post(
        f"/api/v1/products/{product.id}/real-product-video/production-batches/{batch_id}/cancel"
    ).json()
    assert cancelled["batch"]["status"] == "CANCELLED"
    assert {item["status"] for item in cancelled["items"]} == {"CANCELLED"}


def test_production_batch_rejects_tampering_and_cross_product_recovery(
    client: TestClient, db_session: Session, tmp_path
) -> None:
    product, asset, selections = create_three_platform_sources(db_session)
    app.dependency_overrides[get_settings] = lambda: _settings(tmp_path)
    payload = {
        "reference_product_asset_id": asset.id,
        "reference_product_asset_sha256": asset.sha256,
        "selections": selections,
    }
    checked = client.post(
        f"/api/v1/products/{product.id}/real-product-video/three-platform-preflight",
        json=payload,
    ).json()
    wrong = client.post(
        f"/api/v1/products/{product.id}/real-product-video/production-batches",
        json={
            **payload,
            "input_digest": "f" * 64,
            "idempotency_key": "production-batch-tampered",
            "cost_confirmed": True,
        },
    )
    assert wrong.status_code == 409
    assert (
        db_session.scalar(select(func.count()).select_from(ProductVideoProductionBatch))
        == 0
    )

    created = client.post(
        f"/api/v1/products/{product.id}/real-product-video/production-batches",
        json={
            **payload,
            "input_digest": checked["input_digest"],
            "idempotency_key": "production-batch-safe-404",
            "cost_confirmed": True,
        },
    ).json()
    missing = client.get(
        "/api/v1/products/999999/real-product-video/production-batches/"
        f"{created['batch']['id']}"
    )
    assert missing.status_code == 404
    safe = missing.text.casefold()
    assert all(word not in safe for word in ("sql", "select ", "path", "traceback"))
