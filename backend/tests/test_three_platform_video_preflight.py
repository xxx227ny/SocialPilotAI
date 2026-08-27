import hashlib
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    BatchVideoJob,
    BatchVideoVariant,
    ExecutionJob,
    MarketingStrategy,
    Product,
    ProductAsset,
    VideoProject,
    VideoScriptVersion,
    VideoStoryboardSceneVersion,
)
from app.services.video_script_preflight import _model_payload, stable_digest


def create_three_platform_sources(
    session: Session,
    product_profile: dict[str, object] | None = None,
) -> tuple[Product, ProductAsset, list]:
    profile = {
        "name": "Generic Demo Product",
        "category": "Consumer product",
        "description": "A generic product used to verify three-platform production.",
        "selling_points": ["Portable", "Durable"],
        "concept": "Demonstrate the real product benefit",
        "hook": "See the product in action",
        "narration": "A concise product demonstration.",
        "subtitle": "Product demonstration",
        "visual": "Show the complete product",
        "action": "Demonstrate a supported product action",
    }
    profile.update(product_profile or {})
    product = Product(
        name=str(profile["name"]),
        category=str(profile["category"]),
        description=str(profile["description"]),
        selling_points=list(profile["selling_points"]),
        target_markets=["US"],
    )
    session.add(product)
    session.flush()
    strategy = MarketingStrategy(
        product_id=product.id,
        positioning="Practical product value",
        audience_insights=["People who value useful demonstrations"],
        angles=["Show the product solving a real problem"],
        risks=["Avoid unsupported claims"],
        evidence=["Use the frozen product facts"],
    )
    session.add(strategy)
    session.flush()
    strategy_digest = stable_digest(
        _model_payload(
            strategy,
            (
                "id",
                "product_id",
                "positioning",
                "audience_insights",
                "angles",
                "risks",
                "evidence",
            ),
        )
    )
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
            strategy_id=strategy.id,
            strategy_digest=strategy_digest,
            platform=platform,
            language="en-US",
            title=f"{platform} · {profile['name']}",
            concept=str(profile["concept"]),
            hook=str(profile["hook"]),
            full_narration=str(profile["narration"]),
            cta="Learn more",
            full_subtitle_draft=str(profile["narration"]),
            created_by_kind="QWEN_PROVIDER",
            review_status="UNREVIEWED",
            provider_name="qwen",
            provider_model="qwen3.7-plus",
        )
        version.scenes = [
            VideoStoryboardSceneVersion(
                sequence=sequence,
                start_ms=start_ms,
                end_ms=end_ms,
                shot_type="product_demo",
                visual_description=str(profile["visual"]),
                action_description=str(profile["action"]),
                narration=str(profile["narration"]),
                subtitle_draft=str(profile["subtitle"]),
            )
            for sequence, (start_ms, end_ms) in enumerate(((0, 7000), (7000, 15000)), 1)
        ]
        session.add(version)
        session.flush()
        variant.active_script_version_id = version.id
        variant.script_version_sequence = 1
        selections.append({"variant_id": variant.id, "script_version_id": version.id})
    session.commit()
    return product, asset, selections


def test_product_video_sources_expose_authoritative_narration_digest(
    client: TestClient, db_session: Session
) -> None:
    product, _, _ = create_three_platform_sources(db_session)
    settings = Settings(_env_file=None, enable_real_product_video=True)
    app.dependency_overrides[get_settings] = lambda: settings

    response = client.get(f"/api/v1/products/{product.id}/real-product-video/sources")

    assert response.status_code == 200
    sources = response.json()
    assert len(sources) == 3
    for source in sources:
        narration = source["full_narration"]
        assert (
            source["narration_digest"]
            == hashlib.sha256(narration.encode("utf-8")).hexdigest()
        )
        reconstructed = "\n".join(
            scene["narration"].strip() for scene in source["scenes"]
        )
        assert (
            source["narration_digest"]
            != hashlib.sha256(reconstructed.encode("utf-8")).hexdigest()
        )


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
    assert response.json()["dynamic_video_provider"] == "wanx_i2v"
    assert "video_render_execution_disabled" in response.json()["missing_requirements"]
    assert (
        "happyhorse_execution_disabled" not in response.json()["missing_requirements"]
    )
    assert "qwen_credentials" in response.json()["missing_requirements"]
    assert "wanx_credentials" in response.json()["missing_requirements"]


def test_three_platform_preflight_rejects_missing_strategy_before_provider_calls(
    client: TestClient, db_session: Session, tmp_path
) -> None:
    product, asset, selections = create_three_platform_sources(db_session)
    db_session.execute(
        update(VideoScriptVersion)
        .where(VideoScriptVersion.id == selections[0]["script_version_id"])
        .values(strategy_id=None, strategy_digest=None)
        .execution_options(synchronize_session=False)
    )
    db_session.commit()
    db_session.expire_all()
    app.dependency_overrides[get_settings] = lambda: Settings(
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
    )
    before = int(db_session.scalar(select(func.count()).select_from(ExecutionJob)) or 0)

    response = client.post(
        f"/api/v1/products/{product.id}/real-product-video/three-platform-preflight",
        json={
            "reference_product_asset_id": asset.id,
            "reference_product_asset_sha256": asset.sha256,
            "selections": selections,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == (
        "ScriptVersion lacks exact Strategy identity"
    )
    assert (
        int(db_session.scalar(select(func.count()).select_from(ExecutionJob)) or 0)
        == before
    )


def test_youtube_script_without_copy_matrix_prepares_exact_video_project(
    client: TestClient, db_session: Session, tmp_path
) -> None:
    product, asset, selections = create_three_platform_sources(db_session)
    youtube = next(
        selection
        for selection in selections
        if db_session.get(BatchVideoVariant, selection["variant_id"]).platform
        == "youtube"
    )
    version = db_session.get(VideoScriptVersion, youtube["script_version_id"])
    assert version.copy_matrix_id is None
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        enable_real_product_video=True,
        product_asset_storage_root=str(tmp_path / "images"),
        video_artifact_storage_root=str(tmp_path / "videos"),
    )

    response = client.post(
        f"/api/v1/products/{product.id}/real-product-video/prepare",
        json={
            "variant_id": youtube["variant_id"],
            "script_version_id": youtube["script_version_id"],
            "platform": "YOUTUBE_SHORTS",
            "shots": [
                {
                    "scene_id": scene.id,
                    "product_asset_id": asset.id,
                    "product_asset_sha256": asset.sha256,
                    "motion": "zoom_in",
                }
                for scene in version.scenes
            ],
        },
    )

    assert response.status_code == 200
    project = db_session.get(VideoProject, response.json()["video_project_id"])
    assert project is not None
    assert project.marketing_strategy_id == version.strategy_id
    assert project.copy_matrix_id is None
    assert project.source_script_version_id == version.id
