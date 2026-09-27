import json
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.execution.worker import WorkerRunStatus
from app.main import app
from app.models import BatchVideoVariant, ExecutionAttempt, ExecutionJob
from app.schemas.video_script_version import (
    QwenScriptPreflightRead,
    QwenScriptProviderOutput,
)
from app.services.video_script_version_service import VideoScriptVersionService
from tests.test_qwen_video_script_preflight import qwen_settings, strategy_for
from tests.test_qwen_video_script_queue_e2e import FakeQwen, worker
from tests.test_video_script_preflight import ready_variant

CHINESE_RESPONSE = json.dumps(
    {
        "title": "桌面工作灯",
        "concept": "展示照明和充电操作",
        "hook": "桌面更整洁",
        "cta": "查看商品详情",
        "scenes": [
            {
                "sequence": 1,
                "start_ms": 0,
                "end_ms": 3000,
                "shot_type": "wide",
                "visual_description": "展示商品",
                "action_description": "打开台灯",
                "narration": "桌面照明充电一步到位。",
                "subtitle_draft": "桌面照明充电一步到位。",
            },
            {
                "sequence": 2,
                "start_ms": 3000,
                "end_ms": 8000,
                "shot_type": "close",
                "visual_description": "展示灯臂与亮度调节",
                "action_description": "调节灯臂并放置手机",
                "narration": "展开灯臂，调节亮度，同时为手机无线充电。",
                "subtitle_draft": "展开灯臂，调节亮度，同时为手机无线充电。",
            },
            {
                "sequence": 3,
                "start_ms": 8000,
                "end_ms": 12000,
                "shot_type": "proof",
                "visual_description": "展示底座与触控操作",
                "action_description": "操作触控按键",
                "narration": "稳固底座节省空间，触控操作简单清晰。",
                "subtitle_draft": "稳固底座节省空间，触控操作简单清晰。",
            },
            {
                "sequence": 4,
                "start_ms": 12000,
                "end_ms": 15000,
                "shot_type": "hero",
                "visual_description": "展示完整商品",
                "action_description": "呈现商品和行动指引",
                "narration": "选择GlowNest，让桌面更整洁。",
                "subtitle_draft": "选择GlowNest，让桌面更整洁。",
            },
        ],
    },
    ensure_ascii=False,
)


def three_ready_variants(session):
    first = ready_variant(session)
    first.batch.variant_count = 3
    first.batch.max_concurrency = 3
    first.batch.qwen_script_call_quota = 3
    variants = [first]
    for index, platform in enumerate(("tiktok", "instagram"), 2):
        variant = BatchVideoVariant(
            batch_video_job_id=first.batch_video_job_id,
            product_id=first.product_id,
            platform=platform,
            variant_index=1,
            duration_seconds=15,
            aspect_ratio="9:16",
            language="zh-CN",
            creative_angle="proof",
            brand_kit_version_id=first.brand_kit_version_id,
            brand_kit_version_digest=first.brand_kit_version_digest,
            source_digest=f"{index + 700:064x}",
            idempotency_key=f"batch-qwen-variant-{index}",
            status="READY_FOR_SCRIPT",
            result_entity_type="BatchVideoVariant",
            result_entity_id=index,
        )
        session.add(variant)
        variants.append(variant)
    session.commit()
    return first.batch, variants


def test_batch_qwen_preflight_enqueue_recover_and_activate_exact_versions(
    client, db_session
) -> None:
    batch, variants = three_ready_variants(db_session)
    strategy = strategy_for(db_session, variants[0].product_id)
    settings = qwen_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    request = {
        "product_id": variants[0].product_id,
        "variant_ids": [item.id for item in variants],
        "strategy_id": strategy.id,
        "copy_matrix_id": None,
    }
    before = (
        db_session.query(ExecutionJob).count(),
        batch.qwen_script_calls_reserved,
    )

    checked_response = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts/preflight",
        json=request,
    )
    assert checked_response.status_code == 200
    checked = checked_response.json()
    assert checked["ready_for_execution"] is True
    assert checked["estimated_provider_calls"] == 3
    assert checked["estimated_cost_min"] == "0.06"
    assert checked["estimated_cost_max"] == "0.24"
    assert checked["wanx_image_generation_calls"] == 12
    assert checked["happyhorse_generation_calls"] == 0
    assert checked["dynamic_video_generation_calls"] == 3
    assert checked["dynamic_video_provider"] == "wanx_i2v"
    assert checked["dynamic_video_model"] == "wan2.6-i2v-flash"
    assert checked["qwen_tts_generation_calls"] == 3
    assert checked["known_downstream_cost"] == "7.95"
    assert checked["total_known_cost_min"] == "8.01"
    assert checked["total_known_cost_max"] == "8.19"
    assert checked["cost_estimate_complete"] is False
    assert checked["unpriced_cost_components"] == ["qwen_tts"]
    assert checked["will_auto_activate_exact_results"] is True
    assert checked["provider_call_count"] == checked["database_writes"] == 0
    assert (
        db_session.query(ExecutionJob).count(),
        batch.qwen_script_calls_reserved,
    ) == before

    create = {
        **request,
        "preflight_digest": checked["preflight_digest"],
        "preflight_expires_at": checked["expires_at"],
        "cost_confirmed": True,
    }
    created_response = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts", json=create
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["status"] == "RUNNING"
    assert {item["status"] for item in created["items"]} == {"QUEUED"}
    assert len({item["job"]["id"] for item in created["items"]}) == 3
    assert db_session.query(ExecutionJob).count() == 3
    db_session.refresh(batch)
    assert batch.qwen_script_calls_reserved == 3

    repeated = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts", json=create
    )
    assert repeated.status_code == 201
    assert [item["job"]["id"] for item in repeated.json()["items"]] == [
        item["job"]["id"] for item in created["items"]
    ]
    assert db_session.query(ExecutionJob).count() == 3

    factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False
    )
    fake = FakeQwen(CHINESE_RESPONSE)
    execution_worker = worker(factory, fake, settings)
    assert [execution_worker.run_once().status for _ in range(3)] == [
        WorkerRunStatus.SUCCEEDED,
        WorkerRunStatus.SUCCEEDED,
        WorkerRunStatus.SUCCEEDED,
    ]
    assert execution_worker.run_once().status == WorkerRunStatus.NO_JOB
    assert fake.calls == 3

    recovery_checked_response = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts/preflight",
        json=request,
    )
    assert recovery_checked_response.status_code == 200
    recovery_checked = recovery_checked_response.json()
    assert recovery_checked["ready_for_execution"] is True
    assert all(item["ready_for_execution"] for item in recovery_checked["items"])
    assert all(item["quota_remaining"] == 0 for item in recovery_checked["items"])
    assert recovery_checked["estimated_provider_calls"] == 0
    assert recovery_checked["estimated_cost_min"] == "0.00"
    assert recovery_checked["estimated_cost_max"] == "0.00"
    assert db_session.query(ExecutionJob).count() == 3

    recovery_create = {
        **request,
        "preflight_digest": recovery_checked["preflight_digest"],
        "preflight_expires_at": recovery_checked["expires_at"],
        "cost_confirmed": True,
    }

    recovered_response = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts", json=recovery_create
    )
    assert recovered_response.status_code == 201
    recovered = recovered_response.json()
    assert recovered["status"] == "READY"
    assert {item["status"] for item in recovered["items"]} == {"READY"}
    assert all(item["active"] for item in recovered["items"])
    assert len({item["script_version_id"] for item in recovered["items"]}) == 3
    db_session.expire_all()
    expected_versions = {
        item["variant_id"]: item["script_version_id"] for item in recovered["items"]
    }
    assert {
        item.id: db_session.get(BatchVideoVariant, item.id).active_script_version_id
        for item in variants
    } == expected_versions
    assert db_session.query(ExecutionJob).count() == 3
    assert db_session.query(ExecutionAttempt).count() == 3
    assert (
        sum(
            item.provider_call_count
            for item in db_session.query(ExecutionAttempt).all()
        )
        == 3
    )


def test_batch_qwen_rejects_cross_batch_or_incomplete_platform_identity(
    client, db_session
) -> None:
    batch, variants = three_ready_variants(db_session)
    other = ready_variant(db_session)
    strategy = strategy_for(db_session, variants[0].product_id)
    app.dependency_overrides[get_settings] = lambda: qwen_settings()
    invalid = {
        "product_id": variants[0].product_id,
        "variant_ids": [variants[0].id, variants[1].id, other.id],
        "strategy_id": strategy.id,
        "copy_matrix_id": None,
    }
    response = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts/preflight",
        json=invalid,
    )
    assert response.status_code == 409
    assert db_session.query(ExecutionJob).count() == 0
    assert batch.qwen_script_calls_reserved == 0


def test_single_platform_qwen_preflight_has_single_platform_costs(
    client, db_session
) -> None:
    batch, variants = three_ready_variants(db_session)
    strategy = strategy_for(db_session, variants[0].product_id)
    app.dependency_overrides[get_settings] = lambda: qwen_settings()
    before = db_session.query(ExecutionJob).count()

    response = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts/preflight",
        json={
            "product_id": variants[0].product_id,
            "variant_ids": [variants[0].id],
            "strategy_id": strategy.id,
            "copy_matrix_id": None,
        },
    )

    assert response.status_code == 200
    checked = response.json()
    assert checked["variant_ids"] == [variants[0].id]
    assert checked["estimated_provider_calls"] == 1
    assert checked["wanx_image_generation_calls"] == 4
    assert checked["dynamic_video_generation_calls"] == 1
    assert checked["qwen_tts_generation_calls"] == 1
    assert checked["known_downstream_cost"] == "2.65"
    assert checked["total_known_cost_min"] == "2.67"
    assert checked["total_known_cost_max"] == "2.73"
    assert db_session.query(ExecutionJob).count() == before


def test_batch_qwen_does_not_recover_legacy_english_result_for_chinese_variant(
    client, db_session
) -> None:
    batch, variants = three_ready_variants(db_session)
    batch.qwen_script_call_quota = 1
    strategy = strategy_for(db_session, variants[0].product_id)
    settings = qwen_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    request = {
        "product_id": variants[0].product_id,
        "variant_ids": [variants[0].id],
        "strategy_id": strategy.id,
        "copy_matrix_id": None,
    }

    checked_response = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts/preflight",
        json=request,
    )
    assert checked_response.status_code == 200
    checked = checked_response.json()
    created_response = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts",
        json={
            **request,
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
            "cost_confirmed": True,
        },
    )
    assert created_response.status_code == 201
    job = db_session.get(ExecutionJob, created_response.json()["items"][0]["job"]["id"])
    assert job is not None
    version = VideoScriptVersionService(db_session).create_qwen_generated(
        checked=QwenScriptPreflightRead.model_validate(checked["items"][0]),
        output=QwenScriptProviderOutput.model_validate_json(FakeQwen().response),
        execution_job_id=job.id,
        prompt_snapshot={},
        prompt_digest="a" * 64,
        provider_response_digest="b" * 64,
    )
    job.status = "SUCCEEDED"
    job.completed_at = datetime.now(UTC)
    job.provider_name = "qwen"
    job.result_entity_type = "video_script_version"
    job.result_entity_id = version.id
    db_session.commit()

    recovery_response = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts/preflight",
        json=request,
    )
    assert recovery_response.status_code == 200
    recovery = recovery_response.json()
    assert recovery["ready_for_execution"] is False
    assert recovery["items"][0]["quota_remaining"] == 0
    assert recovery["estimated_provider_calls"] == 1

    rejected = client.post(
        f"/api/v1/batch-video-jobs/{batch.id}/qwen-scripts",
        json={
            **request,
            "preflight_digest": recovery["preflight_digest"],
            "preflight_expires_at": recovery["expires_at"],
            "cost_confirmed": True,
        },
    )
    assert rejected.status_code == 409
    db_session.refresh(variants[0])
    assert variants[0].active_script_version_id is None
