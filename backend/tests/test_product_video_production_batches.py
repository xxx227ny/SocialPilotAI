import hashlib
import io
import json
import zipfile
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    ExecutionJob,
    MarketingStrategy,
    ProductAsset,
    ProductVideoProductionBatch,
    ProductVideoProductionItem,
    VideoComposition,
    VideoCompositionArtifact,
    VideoCompositionAudioArtifact,
    VideoCompositionEnhancement,
    VideoCompositionEnhancementArtifact,
    VideoCompositionSubtitleArtifact,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.services.product_video_production_batch_service import (
    ProductVideoProductionBatchService,
)
from app.services.video_artifact_storage import LocalVideoArtifactStorage
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


def test_legacy_provider_profile_unlocks_wanx_i2v_batch_creation(
    client: TestClient, db_session: Session, tmp_path
) -> None:
    product, asset, selections = create_three_platform_sources(db_session)
    settings = _settings(tmp_path).model_copy(
        update={"enable_happyhorse_product_video": False}
    )
    app.dependency_overrides[get_settings] = lambda: settings
    payload = {
        "reference_product_asset_id": asset.id,
        "reference_product_asset_sha256": asset.sha256,
        "selections": selections,
    }

    checked_response = client.post(
        f"/api/v1/products/{product.id}/real-product-video/three-platform-preflight",
        json=payload,
    )
    assert checked_response.status_code == 200
    checked = checked_response.json()
    assert checked["ready"] is True
    assert checked["dynamic_video_provider"] == "wanx_i2v"
    assert checked["dynamic_video_generation_calls"] == 3
    assert checked["happyhorse_generation_calls"] == 0

    created = client.post(
        f"/api/v1/products/{product.id}/real-product-video/production-batches",
        json={
            **payload,
            "input_digest": checked["input_digest"],
            "idempotency_key": "production-batch-wanx-i2v-1",
            "cost_confirmed": True,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["batch"]["status"] == "WAITING"
    assert {
        item["stage_state_json"]["dynamic_video_provider"] for item in body["items"]
    } == {"wanx_i2v"}


def test_resume_repairs_legacy_guarded_wanx_task_without_resubmission(
    client: TestClient, db_session: Session, tmp_path
) -> None:
    product, asset, selections = create_three_platform_sources(db_session)
    settings = _settings(tmp_path).model_copy(
        update={"enable_happyhorse_product_video": False}
    )
    app.dependency_overrides[get_settings] = lambda: settings
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
            "idempotency_key": "production-batch-legacy-guarded-wanx",
            "cost_confirmed": True,
        },
    ).json()
    batch = db_session.get(ProductVideoProductionBatch, created["batch"]["id"])
    item = db_session.get(ProductVideoProductionItem, created["items"][0]["id"])
    strategy = (
        db_session.query(MarketingStrategy).filter_by(product_id=product.id).one()
    )
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=strategy.id,
        platform="TikTok",
        title="Frozen product demo",
        concept="Exact legacy recovery",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[],
        cta="Learn more",
        status="planned",
    )
    db_session.add(project)
    db_session.flush()
    task = VideoRenderTask(
        video_project_id=project.id,
        scene_sequence=1,
        status="PENDING",
        provider_name="_contextvisual",
        provider_task_id="existing-wanx-provider-task",
        render_prompt="Frozen exact product motion",
        duration_seconds=15,
        aspect_ratio="9:16",
        resolution="720P",
        idempotency_key="legacy-context-provider-task",
        source_product_asset_id=asset.id,
        source_product_asset_sha256=asset.sha256,
    )
    db_session.add(task)
    db_session.flush()
    job = ExecutionJob(
        job_type="wanx.video_render.submit.v1",
        source_type="video_project",
        source_id=project.id,
        input_digest="a" * 64,
        idempotency_key="legacy-context-provider-submit-job",
        input_payload={},
        estimated_cost=Decimal("2.25"),
        currency="CNY",
        cost_confirmed=True,
        status="SUCCEEDED",
        attempt_count=1,
        max_attempts=1,
        provider_name="wanx",
        result_entity_type="video_render_task",
        result_entity_id=task.id,
        completed_at=item.created_at,
    )
    db_session.add(job)
    db_session.flush()
    item.video_project_id = project.id
    item.status = "FAILED"
    item.stage = "GENERATING_VIDEO"
    item.safe_error_code = "PRODUCTION_WANX_VIDEO_RESULT_INVALID"
    item.completed_at = item.created_at
    item.stage_state_json = {
        **item.stage_state_json,
        "dynamic_video_submit_job_id": job.id,
    }
    batch.status = "FAILED"
    batch.completed_at = batch.created_at
    db_session.commit()
    job_count = db_session.query(ExecutionJob).count()

    resumed = client.post(
        f"/api/v1/products/{product.id}/real-product-video/"
        f"production-batches/{batch.id}/resume"
    )

    assert resumed.status_code == 200
    body = resumed.json()
    recovered = next(value for value in body["items"] if value["id"] == item.id)
    assert body["batch"]["status"] == "RUNNING"
    assert recovered["status"] == "RUNNING"
    assert recovered["safe_error_code"] is None
    assert recovered["cloud_render_task_id"] == task.id
    db_session.refresh(task)
    assert task.provider_name == "wanx"
    assert db_session.query(ExecutionJob).count() == job_count


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


@pytest.mark.parametrize(
    "product_profile",
    [
        pytest.param(None, id="generic-consumer-product"),
        pytest.param(
            {
                "name": "Smart Pet Feeder",
                "category": "Pet care appliance",
                "description": (
                    "A sealed automatic feeder that serves scheduled portions."
                ),
                "selling_points": [
                    "Scheduled portions",
                    "Sealed food storage",
                    "Easy-clean bowl",
                ],
                "concept": "Show a calm, reliable feeding routine",
                "hook": "Never miss a scheduled meal",
                "narration": (
                    "Serve consistent portions on schedule and keep food protected."
                ),
                "subtitle": "Scheduled portions. Protected food.",
                "visual": "Show the complete feeder beside a pet dining area",
                "action": "Dispense one measured portion into the visible bowl",
            },
            id="smart-pet-feeder",
        ),
    ],
)
def test_advance_enqueues_wanx_jobs_once_and_recovers_exact_assets(
    client: TestClient,
    db_session: Session,
    tmp_path,
    product_profile: dict[str, object] | None,
) -> None:
    product, asset, selections = create_three_platform_sources(
        db_session, product_profile
    )
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
            "idempotency_key": "production-batch-advance-wanx",
            "cost_confirmed": True,
        },
    ).json()
    batch_id = created["batch"]["id"]
    endpoint = (
        f"/api/v1/products/{product.id}/real-product-video/"
        f"production-batches/{batch_id}/advance"
    )

    advanced = client.post(endpoint)
    assert advanced.status_code == 200
    body = advanced.json()
    assert body["batch"]["status"] == "RUNNING"
    assert {item["stage"] for item in body["items"]} == {"GENERATING_IMAGES"}
    assert all(
        len(item["stage_state_json"]["wanx_job_ids"]) == 2 for item in body["items"]
    )
    jobs = (
        db_session.query(ExecutionJob)
        .filter_by(job_type="wanx.product_image.generate.v1")
        .order_by(ExecutionJob.id)
        .all()
    )
    assert len(jobs) == 6
    assert {job.status for job in jobs} == {"QUEUED"}
    assert sum(job.estimated_cost for job in jobs) == Decimal("0.60")
    for job in jobs:
        prompt = job.input_payload["prompt"]
        assert product.name in prompt
        assert product.category in prompt
        assert all(point in prompt for point in product.selling_points)
        assert all(
            forbidden not in prompt.casefold()
            for forbidden in ("blender", "smoothie", "juicer", "榨汁")
        )
    before_updated_at = {
        item.id: item.updated_at
        for item in db_session.query(ProductVideoProductionItem).all()
    }

    repeated = client.post(endpoint)
    assert repeated.status_code == 200
    assert db_session.query(ExecutionJob).count() == 6
    assert {
        item.id: item.updated_at
        for item in db_session.query(ProductVideoProductionItem).all()
    } == before_updated_at
    for first, second in zip(body["items"], repeated.json()["items"], strict=True):
        assert {key: value for key, value in first.items() if key != "updated_at"} == {
            key: value for key, value in second.items() if key != "updated_at"
        }

    for index, job in enumerate(jobs, 1):
        generated = ProductAsset(
            product_id=product.id,
            file_name=f"generated-{index}.png",
            file_path=f"product-images/generated-{index}.png",
            file_type="png",
            content_type="image/png",
            size_bytes=100 + index,
            sha256=f"{index:x}" * 64,
            width=720,
            height=1280,
            storage_identity=f"product-images/generated-{index}.png",
        )
        db_session.add(generated)
        db_session.flush()
        job.status = "SUCCEEDED"
        job.result_entity_type = "product_asset"
        job.result_entity_id = generated.id
        job.completed_at = job.created_at
    db_session.commit()

    recovered = client.post(endpoint)
    assert recovered.status_code == 200
    assert {item["stage"] for item in recovered.json()["items"]} == {"PREPARING_VIDEO"}
    assert all(
        len(item["stage_state_json"]["wanx_product_asset_ids"]) == 2
        for item in recovered.json()["items"]
    )
    assert db_session.query(ExecutionJob).count() == 6

    submitted = client.post(endpoint)
    assert submitted.status_code == 200
    submitted_body = submitted.json()
    assert {item["stage"] for item in submitted_body["items"]} == {"GENERATING_VIDEO"}
    assert db_session.query(VideoProject).count() == 3
    submit_jobs = (
        db_session.query(ExecutionJob)
        .filter_by(job_type="happyhorse.product_video.submit.v1")
        .order_by(ExecutionJob.id)
        .all()
    )
    assert len(submit_jobs) == 3
    assert db_session.query(ExecutionJob).count() == 9
    assert all(
        item["stage_state_json"]["happyhorse_submit_job_id"]
        in {job.id for job in submit_jobs}
        for item in submitted_body["items"]
    )

    repeated_submit = client.post(endpoint)
    assert repeated_submit.status_code == 200
    assert db_session.query(VideoProject).count() == 3
    assert db_session.query(ExecutionJob).count() == 9

    for item in submitted_body["items"]:
        job = db_session.get(
            ExecutionJob, item["stage_state_json"]["happyhorse_submit_job_id"]
        )
        task = VideoRenderTask(
            video_project_id=item["video_project_id"],
            scene_sequence=1,
            status="PENDING",
            provider_name="happyhorse",
            provider_task_id=f"provider-task-{item['id']}",
            render_prompt="Frozen generic product demonstration",
            duration_seconds=15,
            aspect_ratio="9:16",
            resolution="720P",
            idempotency_key=f"production-happyhorse-task-{item['id']}",
        )
        db_session.add(task)
        db_session.flush()
        job.status = "SUCCEEDED"
        job.result_entity_type = "video_render_task"
        job.result_entity_id = task.id
        job.completed_at = job.created_at
    db_session.commit()

    task_recovery = client.post(endpoint)
    assert task_recovery.status_code == 200
    assert all(
        item["cloud_render_task_id"] is not None
        for item in task_recovery.json()["items"]
    )
    assert db_session.query(ExecutionJob).count() == 9

    retryable_item_read = task_recovery.json()["items"][0]
    retryable_item = db_session.get(
        ProductVideoProductionItem, retryable_item_read["id"]
    )
    retryable_task = db_session.get(
        VideoRenderTask, retryable_item_read["cloud_render_task_id"]
    )
    retryable_batch = db_session.get(ProductVideoProductionBatch, batch_id)
    retryable_task.error_code = "refresh_quota_or_rate_limit"
    retryable_item.status = "FAILED"
    retryable_item.safe_error_code = "PRODUCTION_HAPPYHORSE_REFRESH_RETRYABLE"
    retryable_item.completed_at = retryable_item.created_at
    retryable_batch.status = "PARTIAL_FAILED"
    db_session.commit()

    retried = client.post(
        f"/api/v1/products/{product.id}/real-product-video/"
        f"production-batches/{batch_id}/resume"
    )
    assert retried.status_code == 200
    retried_body = retried.json()
    recovered_item = next(
        item for item in retried_body["items"] if item["id"] == retryable_item.id
    )
    assert retried_body["batch"]["status"] == "RUNNING"
    assert recovered_item["status"] == "RUNNING"
    assert recovered_item["safe_error_code"] is None
    assert recovered_item["completed_at"] is None
    assert recovered_item["stage_state_json"]["happyhorse_refresh_job_id"] is None

    refresh_submit = client.post(endpoint)
    assert refresh_submit.status_code == 200
    refresh_items = refresh_submit.json()["items"]
    refresh_jobs = (
        db_session.query(ExecutionJob)
        .filter_by(job_type="happyhorse.product_video.refresh.v1")
        .order_by(ExecutionJob.id)
        .all()
    )
    assert len(refresh_jobs) == 3
    assert db_session.query(ExecutionJob).count() == 12
    assert all(
        item["stage_state_json"]["happyhorse_refresh_count"] == 1
        and item["stage_state_json"]["happyhorse_refresh_job_id"]
        in {job.id for job in refresh_jobs}
        for item in refresh_items
    )

    repeated_refresh = client.post(endpoint)
    assert repeated_refresh.status_code == 200
    assert db_session.query(ExecutionJob).count() == 12

    pending_item = refresh_items[0]
    video_storage = LocalVideoArtifactStorage(tmp_path / "videos", 100_000_000)
    for item in refresh_items:
        job = db_session.get(
            ExecutionJob, item["stage_state_json"]["happyhorse_refresh_job_id"]
        )
        task = db_session.get(VideoRenderTask, item["cloud_render_task_id"])
        job.status = "SUCCEEDED"
        job.completed_at = job.created_at
        if item["id"] == pending_item["id"]:
            job.result_entity_type = "video_render_task"
            job.result_entity_id = task.id
            continue
        task.status = "SUCCEEDED"
        stored = video_storage.store(
            task_id=task.id,
            content=f"fake-happyhorse-{item['id']}".encode(),
            content_type="video/mp4",
        )
        artifact = VideoRenderArtifact(
            video_render_task_id=task.id,
            storage_path=stored.relative_path,
            artifact_metadata={
                "content_type": "video/mp4",
                "size_bytes": stored.size_bytes,
                "sha256": stored.sha256,
            },
        )
        db_session.add(artifact)
        db_session.flush()
        job.result_entity_type = "video_render_artifact"
        job.result_entity_id = artifact.id
    db_session.commit()

    first_refresh = client.post(endpoint)
    assert first_refresh.status_code == 200
    by_id = {item["id"]: item for item in first_refresh.json()["items"]}
    assert by_id[pending_item["id"]]["stage"] == "GENERATING_VIDEO"
    assert (
        by_id[pending_item["id"]]["stage_state_json"]["happyhorse_refresh_job_id"]
        is None
    )
    assert {
        item["stage"]
        for item in first_refresh.json()["items"]
        if item["id"] != pending_item["id"]
    } == {"COMPOSING"}

    second_refresh = client.post(endpoint)
    assert second_refresh.status_code == 200
    pending_after = next(
        item
        for item in second_refresh.json()["items"]
        if item["id"] == pending_item["id"]
    )
    assert pending_after["stage_state_json"]["happyhorse_refresh_count"] == 2
    assert db_session.query(ExecutionJob).count() == 15
    final_refresh_job = db_session.get(
        ExecutionJob,
        pending_after["stage_state_json"]["happyhorse_refresh_job_id"],
    )
    pending_task = db_session.get(
        VideoRenderTask, pending_after["cloud_render_task_id"]
    )
    pending_task.status = "RUNNING"
    pending_task.error_code = "refresh_quota_or_rate_limit"
    pending_task.error_message = "Provider result query was rate-limited"
    final_refresh_job.status = "FAILED"
    final_refresh_job.safe_error_code = "HAPPYHORSE_REFRESH_REJECTED"
    final_refresh_job.completed_at = final_refresh_job.created_at
    db_session.commit()

    all_downloaded = client.post(endpoint)
    assert all_downloaded.status_code == 200
    assert {item["stage"] for item in all_downloaded.json()["items"]} == {"COMPOSING"}
    assert all(
        item["cloud_render_artifact_id"] is not None
        for item in all_downloaded.json()["items"]
    )
    assert db_session.query(VideoRenderArtifact).count() == 3
    assert db_session.query(ExecutionJob).count() == 15
    fallback_item = next(
        item
        for item in all_downloaded.json()["items"]
        if item["id"] == pending_item["id"]
    )
    assert (
        fallback_item["stage_state_json"]["visual_fallback"]
        == "same_batch_dynamic_visual"
    )
    fallback_task = db_session.get(
        VideoRenderTask, fallback_item["cloud_render_task_id"]
    )
    fallback_artifact = db_session.get(
        VideoRenderArtifact, fallback_item["cloud_render_artifact_id"]
    )
    assert fallback_task.provider_name == "local_batch_visual_fallback"
    assert fallback_task.status == "SUCCEEDED"
    assert fallback_artifact.artifact_metadata["source_kind"] == (
        "same_batch_dynamic_visual_fallback"
    )

    composition_submitted = client.post(endpoint)
    assert composition_submitted.status_code == 200
    composition_items = composition_submitted.json()["items"]
    assert {item["stage"] for item in composition_items} == {"COMPOSING"}
    assert all(item["composition_id"] is not None for item in composition_items)
    assert db_session.query(VideoComposition).count() == 3
    assert (
        db_session.query(ExecutionJob)
        .filter_by(job_type="video.composition.render.v1")
        .count()
        == 3
    )
    assert db_session.query(ExecutionJob).count() == 16

    repeated_composition = client.post(endpoint)
    assert repeated_composition.status_code == 200
    assert db_session.query(VideoComposition).count() == 3
    assert db_session.query(ExecutionJob).count() == 16

    for item in composition_items:
        job = db_session.get(
            ExecutionJob, item["stage_state_json"]["composition_job_id"]
        )
        composition = db_session.get(VideoComposition, item["composition_id"])
        composition_content = f"composition-{item['id']}".encode()
        composition_name = f"composition-item-{item['id']}.mp4"
        composition_path = tmp_path / "videos" / composition_name
        composition_path.write_bytes(composition_content)
        artifact = VideoCompositionArtifact(
            composition_id=composition.id,
            storage_path=composition_name,
            content_type="video/mp4",
            size_bytes=len(composition_content),
            sha256=hashlib.sha256(composition_content).hexdigest(),
            duration_ms=15000,
            width=1080,
            height=1920,
            fps_numerator=30,
            fps_denominator=1,
            video_codec="h264",
            pixel_format="yuv420p",
            audio_codec="aac",
            audio_sample_rate=48000,
            container="mp4",
            source_chain_digest=composition.source_chain_digest,
        )
        db_session.add(artifact)
        db_session.flush()
        composition.status = "SUCCEEDED"
        composition.completed_at = composition.created_at
        job.status = "SUCCEEDED"
        job.result_entity_type = "video_composition_artifact"
        job.result_entity_id = artifact.id
        job.completed_at = job.created_at
    db_session.commit()

    composition_recovered = client.post(endpoint)
    assert composition_recovered.status_code == 200
    assert {item["stage"] for item in composition_recovered.json()["items"]} == {
        "GENERATING_VOICEOVER"
    }
    assert all(
        item["stage_state_json"]["composition_artifact_id"] > 0
        for item in composition_recovered.json()["items"]
    )
    assert db_session.query(VideoCompositionArtifact).count() == 3
    assert db_session.query(ExecutionJob).count() == 16

    voiceover_submitted = client.post(endpoint)
    assert voiceover_submitted.status_code == 200
    voiceover_items = voiceover_submitted.json()["items"]
    assert {item["stage"] for item in voiceover_items} == {"GENERATING_VOICEOVER"}
    voiceover_jobs = (
        db_session.query(ExecutionJob)
        .filter_by(job_type="tts.voiceover.generate.v1")
        .order_by(ExecutionJob.id)
        .all()
    )
    assert len(voiceover_jobs) == 3
    assert all(
        job.input_payload["target_duration_ms"] == 15000 for job in voiceover_jobs
    )
    assert all(
        job.input_payload["voice"] == _settings(tmp_path).qwen_tts_voice
        for job in voiceover_jobs
    )
    assert all(job.input_payload["speaking_rate"] == 1.08 for job in voiceover_jobs)
    assert db_session.query(ExecutionJob).count() == 19

    timeline_item = db_session.get(
        ProductVideoProductionItem, voiceover_items[-1]["id"]
    )
    timeline_job = db_session.get(
        ExecutionJob, timeline_item.stage_state_json["voiceover_job_id"]
    )
    timeline_job.status = "FAILED"
    timeline_job.safe_error_code = "VOICEOVER_EXCEEDS_TIMELINE"
    timeline_job.safe_error_details = {
        "natural_duration_ms": 15200,
        "target_duration_ms": 15000,
    }
    ProductVideoProductionBatchService(
        db_session, _settings(tmp_path)
    )._recover_voiceover(
        db_session.get(ProductVideoProductionBatch, batch_id),
        timeline_item,
        timeline_job.id,
    )
    assert timeline_item.safe_error_code == "PRODUCTION_VOICEOVER_EXCEEDS_TIMELINE"
    assert timeline_item.stage_state_json["voiceover_timeline_error"] == {
        "natural_duration_ms": 15200,
        "target_duration_ms": 15000,
    }
    timeline_job.status = "QUEUED"
    timeline_job.safe_error_code = None
    timeline_job.safe_error_details = None
    timeline_item.status = "RUNNING"
    timeline_item.safe_error_code = None
    timeline_item.completed_at = None
    timeline_item.stage_state_json = {
        key: value
        for key, value in timeline_item.stage_state_json.items()
        if key != "voiceover_timeline_error"
    }

    repeated_voiceover = client.post(endpoint)
    assert repeated_voiceover.status_code == 200
    assert db_session.query(ExecutionJob).count() == 19

    retry_item = voiceover_items[0]
    failed_voiceover_job = db_session.get(
        ExecutionJob,
        retry_item["stage_state_json"]["voiceover_job_id"],
    )
    failed_voiceover_job.status = "FAILED"
    failed_voiceover_job.safe_error_code = "QWEN_TTS_FAILED"
    failed_voiceover_job.completed_at = failed_voiceover_job.created_at
    db_session.commit()

    retry_prepared = client.post(endpoint)
    assert retry_prepared.status_code == 200
    retry_prepared_item = next(
        item
        for item in retry_prepared.json()["items"]
        if item["id"] == retry_item["id"]
    )
    assert retry_prepared_item["status"] == "RUNNING"
    assert retry_prepared_item["stage"] == "GENERATING_VOICEOVER"
    assert "voiceover_job_id" not in retry_prepared_item["stage_state_json"]
    assert retry_prepared_item["stage_state_json"]["voiceover_retry_count"] == 1

    retry_submitted = client.post(endpoint)
    assert retry_submitted.status_code == 200
    voiceover_items = retry_submitted.json()["items"]
    retried_item = next(
        item for item in voiceover_items if item["id"] == retry_item["id"]
    )
    assert retried_item["stage_state_json"]["voiceover_job_id"] != (
        failed_voiceover_job.id
    )
    assert db_session.query(ExecutionJob).count() == 20

    incompatible_voice_job = db_session.get(
        ExecutionJob, retried_item["stage_state_json"]["voiceover_job_id"]
    )
    incompatible_voice_job.input_payload = {
        **incompatible_voice_job.input_payload,
        "voice": "longanhuan_v3.6",
    }
    incompatible_voice_job.status = "FAILED"
    incompatible_voice_job.safe_error_code = "QWEN_TTS_FAILED"
    incompatible_voice_job.completed_at = incompatible_voice_job.created_at
    terminal_item = db_session.get(ProductVideoProductionItem, retry_item["id"])
    terminal_batch = db_session.get(ProductVideoProductionBatch, batch_id)
    terminal_item.status = "FAILED"
    terminal_item.safe_error_code = "PRODUCTION_VOICEOVER_FAILED"
    terminal_item.completed_at = incompatible_voice_job.completed_at
    terminal_batch.status = "PARTIAL_FAILED"
    terminal_batch.completed_at = incompatible_voice_job.completed_at
    db_session.commit()

    config_retry_prepared = client.post(
        f"/api/v1/products/{product.id}/real-product-video/"
        f"production-batches/{batch_id}/resume"
    )
    assert config_retry_prepared.status_code == 200
    assert config_retry_prepared.json()["batch"]["status"] == "RUNNING"
    config_retry_item = next(
        item
        for item in config_retry_prepared.json()["items"]
        if item["id"] == retry_item["id"]
    )
    assert "voiceover_job_id" not in config_retry_item["stage_state_json"]
    assert config_retry_item["stage_state_json"]["voiceover_config_retry_count"] == 1

    config_retry_submitted = client.post(endpoint)
    assert config_retry_submitted.status_code == 200
    voiceover_items = config_retry_submitted.json()["items"]
    corrected_item = next(
        item for item in voiceover_items if item["id"] == retry_item["id"]
    )
    corrected_job = db_session.get(
        ExecutionJob, corrected_item["stage_state_json"]["voiceover_job_id"]
    )
    assert corrected_job.id != incompatible_voice_job.id
    assert corrected_job.input_payload["voice"] == "longanlingxin"
    assert db_session.query(ExecutionJob).count() == 21

    corrected_job.status = "FAILED"
    corrected_job.safe_error_code = "QWEN_TTS_FAILED"
    corrected_job.safe_error_details = {"category": "rate_limited"}
    corrected_job.uncertain = False
    corrected_job.completed_at = corrected_job.created_at
    terminal_item = db_session.get(ProductVideoProductionItem, retry_item["id"])
    terminal_batch = db_session.get(ProductVideoProductionBatch, batch_id)
    terminal_item.status = "FAILED"
    terminal_item.safe_error_code = "PRODUCTION_VOICEOVER_FAILED"
    terminal_item.completed_at = corrected_job.completed_at
    terminal_batch.status = "PARTIAL_FAILED"
    terminal_batch.completed_at = corrected_job.completed_at
    db_session.commit()

    manual_retry_prepared = client.post(
        f"/api/v1/products/{product.id}/real-product-video/"
        f"production-batches/{batch_id}/resume"
    )
    assert manual_retry_prepared.status_code == 200
    manual_retry_item = next(
        item
        for item in manual_retry_prepared.json()["items"]
        if item["id"] == retry_item["id"]
    )
    assert manual_retry_item["status"] == "RUNNING"
    assert "voiceover_job_id" not in manual_retry_item["stage_state_json"]
    assert (
        manual_retry_item["stage_state_json"]["voiceover_manual_rate_limit_retry_count"]
        == 1
    )

    manual_retry_submitted = client.post(endpoint)
    assert manual_retry_submitted.status_code == 200
    voiceover_items = manual_retry_submitted.json()["items"]
    manual_retried_item = next(
        item for item in voiceover_items if item["id"] == retry_item["id"]
    )
    manual_retried_job = db_session.get(
        ExecutionJob,
        manual_retried_item["stage_state_json"]["voiceover_job_id"],
    )
    assert manual_retried_job.id != corrected_job.id
    assert "manual-rate-limit:1" in manual_retried_job.idempotency_key
    assert db_session.query(ExecutionJob).count() == 22

    manual_retried_job.status = "SUBMIT_UNKNOWN"
    manual_retried_job.safe_error_code = "QWEN_TTS_RESULT_UNKNOWN"
    manual_retried_job.uncertain = True
    manual_retried_job.completed_at = manual_retried_job.created_at
    terminal_item = db_session.get(ProductVideoProductionItem, retry_item["id"])
    terminal_batch = db_session.get(ProductVideoProductionBatch, batch_id)
    terminal_item.status = "FAILED"
    terminal_item.safe_error_code = "PRODUCTION_VOICEOVER_SUBMIT_UNKNOWN"
    terminal_item.completed_at = manual_retried_job.completed_at
    terminal_batch.status = "PARTIAL_FAILED"
    terminal_batch.completed_at = manual_retried_job.completed_at
    db_session.commit()

    unchanged = client.post(
        f"/api/v1/products/{product.id}/real-product-video/"
        f"production-batches/{batch_id}/resume"
    ).json()
    unchanged_item = next(
        item for item in unchanged["items"] if item["id"] == retry_item["id"]
    )
    assert unchanged_item["status"] == "FAILED"
    assert unchanged_item["stage_state_json"]["voiceover_job_id"] == (
        manual_retried_job.id
    )

    confirmed = client.post(
        f"/api/v1/products/{product.id}/real-product-video/"
        f"production-batches/{batch_id}/resume",
        json={"confirm_uncertain_voiceover_replacement": True},
    ).json()
    confirmed_item = next(
        item for item in confirmed["items"] if item["id"] == retry_item["id"]
    )
    assert confirmed_item["status"] == "RUNNING"
    assert "voiceover_job_id" not in confirmed_item["stage_state_json"]
    assert (
        confirmed_item["stage_state_json"]["voiceover_uncertain_replacement_count"] == 1
    )
    assert confirmed_item["stage_state_json"]["voiceover_replaced_unknown_job_ids"] == [
        manual_retried_job.id
    ]
    assert manual_retried_job.status == "SUBMIT_UNKNOWN"
    assert manual_retried_job.uncertain is True

    replacement_submitted = client.post(endpoint)
    assert replacement_submitted.status_code == 200
    voiceover_items = replacement_submitted.json()["items"]
    replacement_item = next(
        item for item in voiceover_items if item["id"] == retry_item["id"]
    )
    replacement_job = db_session.get(
        ExecutionJob, replacement_item["stage_state_json"]["voiceover_job_id"]
    )
    assert replacement_job.id != manual_retried_job.id
    assert "uncertain-replacement:1" in replacement_job.idempotency_key
    assert db_session.query(ExecutionJob).count() == 23

    for item in voiceover_items:
        job = db_session.get(ExecutionJob, item["stage_state_json"]["voiceover_job_id"])
        voice_content = f"voiceover-{item['id']}".encode()
        voice_name = f"voiceover-item-{item['id']}.wav"
        (tmp_path / "videos" / voice_name).write_bytes(voice_content)
        artifact = VideoCompositionAudioArtifact(
            product_id=product.id,
            video_project_id=item["video_project_id"],
            composition_id=item["composition_id"],
            kind="voiceover",
            storage_path=voice_name,
            content_type="audio/wav",
            size_bytes=len(voice_content),
            sha256=hashlib.sha256(voice_content).hexdigest(),
            duration_ms=15000,
            natural_duration_ms=12000,
        )
        db_session.add(artifact)
        db_session.flush()
        job.status = "SUCCEEDED"
        job.result_entity_type = "video_composition_audio_artifact"
        job.result_entity_id = artifact.id
        job.completed_at = job.created_at
    db_session.commit()

    voiceover_recovered = client.post(endpoint)
    assert voiceover_recovered.status_code == 200
    assert {item["stage"] for item in voiceover_recovered.json()["items"]} == {
        "ENHANCING"
    }
    assert all(
        item["voiceover_artifact_id"] is not None
        for item in voiceover_recovered.json()["items"]
    )
    assert db_session.query(VideoCompositionAudioArtifact).count() == 3
    assert db_session.query(ExecutionJob).count() == 23

    enhancement_submitted = client.post(endpoint)
    assert enhancement_submitted.status_code == 200
    enhancement_items = enhancement_submitted.json()["items"]
    assert {item["stage"] for item in enhancement_items} == {"ENHANCING"}
    assert all(
        item["stage_state_json"]["subtitle_timeline_ms"] == 14000
        for item in enhancement_items
    )
    enhancement_jobs = (
        db_session.query(ExecutionJob)
        .filter_by(job_type="video.composition.enhance.v1")
        .order_by(ExecutionJob.id)
        .all()
    )
    assert len(enhancement_jobs) == 3
    assert all(
        job.input_payload["music_artifact_id"] is None for job in enhancement_jobs
    )
    assert db_session.query(VideoCompositionEnhancement).count() == 3
    expected_subtitle = (
        str(product_profile["subtitle"])
        if product_profile is not None
        else "Product demonstration"
    )
    assert all(
        [cue["text"] for cue in enhancement.subtitle_cues_json]
        == [expected_subtitle, expected_subtitle]
        for enhancement in db_session.query(VideoCompositionEnhancement).all()
    )
    assert db_session.query(ExecutionJob).count() == 26

    repeated_enhancement = client.post(endpoint)
    assert repeated_enhancement.status_code == 200
    assert db_session.query(VideoCompositionEnhancement).count() == 3
    assert db_session.query(ExecutionJob).count() == 26

    for item in enhancement_items:
        job = db_session.get(
            ExecutionJob, item["stage_state_json"]["enhancement_job_id"]
        )
        enhancement = db_session.get(
            VideoCompositionEnhancement, item["enhancement_id"]
        )
        subtitle_name = f"subtitle-item-{item['id']}.vtt"
        subtitle_content = (
            "WEBVTT\n\n00:00:00.000 --> 00:00:15.000\n"
            f"{item['platform']} product demonstration\n"
        ).encode()
        (tmp_path / "videos" / subtitle_name).write_bytes(subtitle_content)
        subtitle = VideoCompositionSubtitleArtifact(
            enhancement_id=enhancement.id,
            storage_path=subtitle_name,
            content_type="text/vtt; charset=utf-8",
            size_bytes=len(subtitle_content),
            sha256=hashlib.sha256(subtitle_content).hexdigest(),
            format="webvtt",
            cue_count=2,
        )
        db_session.add(subtitle)
        db_session.flush()
        final_name = f"final-item-{item['id']}.mp4"
        final_content = f"final-video-{item['platform']}".encode()
        (tmp_path / "videos" / final_name).write_bytes(final_content)
        final = VideoCompositionEnhancementArtifact(
            enhancement_id=enhancement.id,
            subtitle_artifact_id=subtitle.id,
            storage_path=final_name,
            content_type="video/mp4",
            size_bytes=len(final_content),
            sha256=hashlib.sha256(final_content).hexdigest(),
            duration_ms=15000,
            width=1080,
            height=1920,
            fps_numerator=30,
            fps_denominator=1,
            video_codec="h264",
            video_profile="high",
            pixel_format="yuv420p",
            audio_codec="aac",
            audio_profile="lc",
            audio_sample_rate=48000,
            audio_channels=2,
            container="mp4",
            measured_lufs_milli=-14000,
            measured_true_peak_millidb=-1000,
            audio_video_sync_offset_ms=0,
            longest_black_segment_ms=0,
            subtitle_format="webvtt",
            subtitle_cue_count=2,
            subtitle_sha256=subtitle.sha256,
            source_chain_digest=enhancement.source_chain_digest,
        )
        db_session.add(final)
        db_session.flush()
        enhancement.status = "SUCCEEDED"
        enhancement.completed_at = enhancement.created_at
        job.status = "SUCCEEDED"
        job.result_entity_type = "video_composition_enhancement_artifact"
        job.result_entity_id = final.id
        job.completed_at = job.created_at
    db_session.commit()

    completed = client.post(endpoint)
    assert completed.status_code == 200
    completed_body = completed.json()
    assert completed_body["batch"]["status"] == "SUCCEEDED"
    assert {item["status"] for item in completed_body["items"]} == {"SUCCEEDED"}
    assert {item["stage"] for item in completed_body["items"]} == {"COMPLETE"}
    assert all(item["final_video_artifact_id"] for item in completed_body["items"])
    assert all(item["subtitle_artifact_id"] for item in completed_body["items"])
    assert db_session.query(ExecutionJob).count() == 26

    downloaded = client.get(
        f"/api/v1/products/{product.id}/real-product-video/"
        f"production-batches/{batch_id}/download"
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
    assert downloaded.headers["content-disposition"] == (
        f'attachment; filename="product-{product.id}-batch-{batch_id}-videos.zip"'
    )
    assert int(downloaded.headers["content-length"]) == len(downloaded.content)
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert archive.namelist() == [
            "tiktok/tiktok.mp4",
            "tiktok/tiktok.vtt",
            "youtube/youtube.mp4",
            "youtube/youtube.vtt",
            "instagram/instagram.mp4",
            "instagram/instagram.vtt",
            "manifest.json",
        ]
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["complete"] is True
        assert manifest["included_platforms"] == [
            "tiktok",
            "youtube",
            "instagram",
        ]
        assert manifest["missing_platforms"] == []


def test_advance_failure_and_controls_are_provider_job_scoped(
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
            "idempotency_key": "production-batch-control-wanx",
            "cost_confirmed": True,
        },
    ).json()
    batch_id = created["batch"]["id"]
    root = (
        f"/api/v1/products/{product.id}/real-product-video/"
        f"production-batches/{batch_id}"
    )
    client.post(f"{root}/advance")

    paused = client.post(f"{root}/pause").json()
    assert paused["batch"]["status"] == "PAUSED"
    assert {job.status for job in db_session.query(ExecutionJob).all()} == {"PAUSED"}
    blocked = client.post(f"{root}/advance")
    assert blocked.status_code == 409
    resumed = client.post(f"{root}/resume").json()
    assert resumed["batch"]["status"] == "RUNNING"
    assert {job.status for job in db_session.query(ExecutionJob).all()} == {"QUEUED"}

    first_job = db_session.query(ExecutionJob).order_by(ExecutionJob.id).first()
    first_job.status = "SUBMIT_UNKNOWN"
    first_job.uncertain = True
    first_job.completed_at = first_job.created_at
    db_session.commit()
    failed = client.post(f"{root}/advance").json()
    assert failed["batch"]["status"] == "PARTIAL_FAILED"
    first_item = next(
        item
        for item in failed["items"]
        if first_job.id in item["stage_state_json"]["wanx_job_ids"]
    )
    assert first_item["status"] == "FAILED"
    assert first_item["safe_error_code"] == "PRODUCTION_WANX_SUBMIT_UNKNOWN"

    cancelled = client.post(f"{root}/cancel").json()
    assert cancelled["batch"]["status"] == "CANCELLED"
    assert {item["status"] for item in cancelled["items"]} == {
        "FAILED",
        "CANCELLED",
    }
    assert all(
        job.status in {"SUBMIT_UNKNOWN", "CANCELLED"}
        for job in db_session.query(ExecutionJob).all()
    )
