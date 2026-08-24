from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    ExecutionJob,
    ProductAsset,
    ProductVideoProductionBatch,
    ProductVideoProductionItem,
    VideoProject,
    VideoRenderTask,
)
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


def test_advance_enqueues_wanx_jobs_once_and_recovers_exact_assets(
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
