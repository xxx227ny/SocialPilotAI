from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    BatchVideoJob,
    BatchVideoVariant,
    ExecutionJob,
    Product,
    ProductAsset,
    VideoScriptVersion,
    VideoStoryboardSceneVersion,
)


def create_three_platform_sources(
    session: Session,
) -> tuple[Product, ProductAsset, list]:
    product = Product(
        name="Generic Demo Product",
        category="Consumer product",
        description="A generic product used to verify three-platform production.",
        selling_points=["Portable", "Durable"],
        target_markets=["US"],
    )
    session.add(product)
    session.flush()
    asset = ProductAsset(
        product_id=product.id,
        file_name="product.png",
        file_path="product-images/aa/frozen.png",
        file_type="png",
        content_type="image/png",
        size_bytes=100,
        sha256="a" * 64,
        width=720,
        height=1280,
        storage_identity="product-images/aa/frozen.png",
    )
    batch = BatchVideoJob(
        request_digest="b" * 64,
        idempotency_key="three-platform-preflight-batch",
        status="READY_FOR_SCRIPT",
        priority=50,
        variant_count=3,
        max_concurrency=3,
        current_stage_cost=Decimal("0"),
        currency="USD",
        cost_scope="orchestration_only",
        downstream_provider_cost_status="NOT_ESTIMATED",
        cost_confirmed=True,
        frozen_constraints_json={},
    )
    session.add_all([asset, batch])
    session.flush()
    selections = []
    for index, platform in enumerate(("tiktok", "youtube", "instagram"), 1):
        variant = BatchVideoVariant(
            batch_video_job_id=batch.id,
            product_id=product.id,
            platform=platform,
            variant_index=1,
            duration_seconds=15,
            aspect_ratio="9:16",
            language="en-US",
            source_digest=f"{index}" * 64,
            idempotency_key=f"three-platform-variant-{platform}",
            status="READY_FOR_SCRIPT",
            result_entity_type="batch_video_variant",
            result_entity_id=index,
        )
        session.add(variant)
        session.flush()
        version = VideoScriptVersion(
            batch_video_variant_id=variant.id,
            version_number=1,
            source_type="QWEN_GENERATED",
            source_digest=f"{index + 3}" * 64,
            content_digest=f"{index + 6}" * 64,
            idempotency_key=f"three-platform-script-{platform}",
            product_id=product.id,
            product_content_digest="c" * 64,
            platform=platform,
            language="en-US",
            title=f"{platform} product demo",
            concept="Demonstrate the real product benefit",
            hook="See the product in action",
            full_narration="A concise product demonstration.",
            cta="Learn more",
            full_subtitle_draft="A concise product demonstration.",
            created_by_kind="QWEN_PROVIDER",
            review_status="UNREVIEWED",
            provider_name="qwen",
            provider_model="qwen3.7-plus",
        )
        version.scenes = [
            VideoStoryboardSceneVersion(
                sequence=scene,
                start_ms=(scene - 1) * 7500,
                end_ms=scene * 7500,
                shot_type="product_demo",
                visual_description="Show the complete product",
                action_description="Demonstrate a supported product action",
                narration="A concise product demonstration.",
                subtitle_draft="Product demonstration",
            )
            for scene in (1, 2)
        ]
        session.add(version)
        session.flush()
        variant.active_script_version_id = version.id
        variant.script_version_sequence = 1
        selections.append({"variant_id": variant.id, "script_version_id": version.id})
    session.commit()
    return product, asset, selections


def test_three_platform_preflight_is_exact_honest_and_zero_write(
    client: TestClient, db_session: Session, tmp_path
) -> None:
    product, asset, selections = create_three_platform_sources(db_session)
    settings = Settings(
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
    app.dependency_overrides[get_settings] = lambda: settings
    before = int(db_session.scalar(select(func.count()).select_from(ExecutionJob)) or 0)

    response = client.post(
        f"/api/v1/products/{product.id}/real-product-video/three-platform-preflight",
        json={
            "reference_product_asset_id": asset.id,
            "reference_product_asset_sha256": asset.sha256,
            "selections": selections,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert [item["platform"] for item in body["platforms"]] == [
        "tiktok",
        "youtube",
        "instagram",
    ]
    assert body["wanx_image_generation_calls"] == 6
    assert body["happyhorse_generation_calls"] == 3
    assert body["qwen_tts_generation_calls"] == 3
    assert body["qwen_script_generation_calls"] == 0
    assert body["provider_call_count"] == 12
    assert body["known_estimated_cost"] == "3.60"
    assert body["cost_estimate_complete"] is False
    assert body["unpriced_cost_components"] == ["qwen_tts"]
    assert body["requires_cost_confirmation"] is True
    assert body["database_writes"] == 0
    assert (
        int(db_session.scalar(select(func.count()).select_from(ExecutionJob)) or 0)
        == before
    )
    assert not db_session.new and not db_session.dirty and not db_session.deleted


def test_three_platform_preflight_reports_missing_execution_requirements(
    client: TestClient, db_session: Session, tmp_path
) -> None:
    product, asset, selections = create_three_platform_sources(db_session)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        enable_real_product_video=True,
        product_asset_storage_root=str(tmp_path / "images"),
        video_artifact_storage_root=str(tmp_path / "videos"),
    )

    response = client.post(
        f"/api/v1/products/{product.id}/real-product-video/three-platform-preflight",
        json={
            "reference_product_asset_id": asset.id,
            "reference_product_asset_sha256": asset.sha256,
            "selections": selections,
        },
    )

    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert "happyhorse_execution_disabled" in response.json()["missing_requirements"]
    assert "qwen_credentials" in response.json()["missing_requirements"]
    assert "wanx_credentials" in response.json()["missing_requirements"]
