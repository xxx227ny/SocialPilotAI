from decimal import Decimal

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    CopyMatrix,
    ExecutionAttempt,
    ExecutionJob,
    MarketingStrategy,
    ProductAsset,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_user_auth=True,
        allow_public_registration=True,
        user_auth_cookie_secure=False,
        user_credential_encryption_key=Fernet.generate_key().decode("ascii"),
    )


def _register(client: TestClient, email: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "workspace-summary-password"},
    )
    assert response.status_code == 201
    return response.json()


def test_workspace_summary_reports_real_counts_without_cross_account_data(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    settings = _settings()
    app.dependency_overrides[get_settings] = lambda: settings
    first_account = _register(client, "summary-first@example.com")
    first_workspace_id = int(first_account["workspace_id"])
    key = client.put(
        "/api/v1/credentials/dashscope",
        json={"api_key": "sk-summary-first-user-key", "region": "cn-beijing"},
    )
    assert key.status_code == 200
    product_response = client.post("/api/v1/products", json=product_payload)
    assert product_response.status_code == 201
    product_id = int(product_response.json()["id"])
    db_session.add(
        ProductAsset(
            product_id=product_id,
            file_name="summary.png",
            file_path="product-images/summary.png",
            file_type="png",
            content_type="image/png",
            size_bytes=123,
            sha256="a" * 64,
            width=64,
            height=64,
            storage_identity="product-images/summary.png",
        )
    )

    strategy = MarketingStrategy(
        product_id=product_id,
        positioning="Workspace-only positioning",
        audience_insights=["Workspace-only audience"],
        angles=["Workspace-only angle"],
        risks=["Workspace-only risk"],
        evidence=["Workspace-only evidence"],
    )
    db_session.add(strategy)
    db_session.flush()
    copy_matrix = CopyMatrix(
        product_id=product_id,
        marketing_strategy_id=strategy.id,
        copies=[
            {
                "platform": platform,
                "hook": "Hook",
                "caption": "Caption",
                "hashtags": ["#test"],
                "cta": "CTA",
            }
            for platform in ("tiktok", "instagram", "facebook")
        ],
    )
    db_session.add(copy_matrix)
    db_session.flush()
    video_project = VideoProject(
        product_id=product_id,
        marketing_strategy_id=strategy.id,
        copy_matrix_id=copy_matrix.id,
        platform="TikTok",
        title="Workspace video",
        concept="Workspace-only video concept",
        duration_seconds=5,
        aspect_ratio="9:16",
        scenes=[{"sequence": 1, "duration_seconds": 5}],
        cta="Try it",
        status="completed",
        source_input_digest="1" * 64,
    )
    db_session.add(video_project)
    db_session.flush()
    render_task = VideoRenderTask(
        video_project_id=video_project.id,
        scene_sequence=1,
        status="SUCCEEDED",
        provider_name="test",
        render_prompt="Workspace-only render",
        duration_seconds=5,
        aspect_ratio="9:16",
        resolution="720P",
        idempotency_key="workspace-summary-render",
    )
    db_session.add(render_task)
    db_session.flush()
    db_session.add(
        VideoRenderArtifact(
            video_render_task_id=render_task.id,
            provider_output_url="https://example.invalid/video.mp4",
            artifact_metadata={"content_type": "video/mp4"},
        )
    )
    for suffix, status in (("active", "QUEUED"), ("attention", "FAILED")):
        db_session.add(
            ExecutionJob(
                workspace_id=first_workspace_id,
                job_type="SUMMARY_TEST",
                source_type="product",
                source_id=product_id,
                input_digest=("2" if suffix == "active" else "3") * 64,
                idempotency_key=f"workspace-summary-{suffix}",
                input_payload={},
                priority=0,
                estimated_cost=Decimal("0"),
                currency="CNY",
                cost_confirmed=False,
                status=status,
                attempt_count=0,
                max_attempts=1,
                uncertain=False,
            )
        )
    ai_jobs = []
    for suffix, job_type, status, cost, currency in (
        ("copy", "qwen.copy_matrix.generate.v1", "SUCCEEDED", "0.05", "CNY"),
        ("image", "wanx.product_image.generate.v1", "FAILED", "0.25", "CNY"),
        ("voice", "tts.voiceover.generate.v1", "SUCCEEDED", "0", "CNY"),
    ):
        job = ExecutionJob(
            workspace_id=first_workspace_id,
            job_type=job_type,
            source_type="product",
            source_id=product_id,
            input_digest=(
                "4" if suffix == "copy" else "5" if suffix == "image" else "6"
            )
            * 64,
            idempotency_key=f"workspace-summary-ai-{suffix}",
            input_payload={},
            priority=0,
            estimated_cost=Decimal(cost),
            currency=currency,
            cost_confirmed=True,
            status=status,
            attempt_count=1,
            max_attempts=1,
            uncertain=False,
        )
        db_session.add(job)
        ai_jobs.append(job)
    db_session.flush()
    for index, job in enumerate(ai_jobs, start=1):
        db_session.add(
            ExecutionAttempt(
                execution_job_id=job.id,
                attempt_number=1,
                status=job.status,
                provider_call_count=index,
                external_submission_possible=False,
                provider_submission_state=(
                    "RESPONSE_RECEIVED"
                    if job.status == "SUCCEEDED"
                    else "EXPLICIT_FAILURE"
                ),
            )
        )
    db_session.commit()

    first_summary = client.get("/api/v1/dashboard/workspace-summary")
    assert first_summary.status_code == 200
    assert first_summary.json() == {
        "data_scope": "current_workspace",
        "ai_calls": 6,
        "ai_job_count": 3,
        "ai_success_count": 2,
        "ai_attention_count": 1,
        "confirmed_estimated_costs": [{"currency": "CNY", "amount": "0.3000"}],
        "api_key_configured": True,
        "api_key_verified": False,
        "product_count": 1,
        "product_asset_count": 1,
        "product_asset_storage_bytes": 123,
        "product_asset_storage_limit_bytes": 250_000_000,
        "strategy_count": 1,
        "copy_matrix_count": 1,
        "video_project_count": 1,
        "video_artifact_count": 1,
        "active_job_count": 1,
        "attention_job_count": 2,
    }

    second = TestClient(app)
    try:
        _register(second, "summary-second@example.com")
        second_summary = second.get("/api/v1/dashboard/workspace-summary")
    finally:
        second.close()
    assert second_summary.status_code == 200
    assert second_summary.json() == {
        "data_scope": "current_workspace",
        "ai_calls": 0,
        "ai_job_count": 0,
        "ai_success_count": 0,
        "ai_attention_count": 0,
        "confirmed_estimated_costs": [],
        "api_key_configured": False,
        "api_key_verified": False,
        "product_count": 0,
        "product_asset_count": 0,
        "product_asset_storage_bytes": 0,
        "product_asset_storage_limit_bytes": 250_000_000,
        "strategy_count": 0,
        "copy_matrix_count": 0,
        "video_project_count": 0,
        "video_artifact_count": 0,
        "active_job_count": 0,
        "attention_job_count": 0,
    }


def test_workspace_summary_requires_a_real_product_account(client: TestClient) -> None:
    response = client.get("/api/v1/dashboard/workspace-summary")

    assert response.status_code == 409
    assert "独立用户账号" in response.json()["detail"]
