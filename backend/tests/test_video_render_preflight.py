from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_visual_generation_provider
from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    Product,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.models.product import utc_now
from tests.test_video_render_service import create_video_project


def preflight_path(project_id: int) -> str:
    return f"/api/v1/video-projects/{project_id}/render-preflight"


def configured_settings(*, execution_enabled: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        wanx_api_key="safe-test-placeholder",
        wanx_workspace_id="safe-test-workspace",
        wanx_region="cn-beijing",
        enable_video_render_execution=execution_enabled,
    )


def count_rows(db_session: Session, model: type) -> int:
    return int(
        db_session.scalar(select(func.count()).select_from(model)) or 0
    )


def test_exact_project_and_preflight_are_read_only(
    client: TestClient,
    db_session: Session,
) -> None:
    project = create_video_project(db_session)
    app.dependency_overrides[get_settings] = configured_settings
    provider_resolutions = 0

    def forbidden_provider():
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("Preflight resolved a Provider")

    app.dependency_overrides[get_visual_generation_provider] = forbidden_provider
    before = (
        count_rows(db_session, VideoRenderTask),
        count_rows(db_session, VideoRenderArtifact),
    )

    exact = client.get(f"/api/v1/video-projects/{project.id}")
    response = client.get(preflight_path(project.id))
    after = (
        count_rows(db_session, VideoRenderTask),
        count_rows(db_session, VideoRenderArtifact),
    )

    assert exact.status_code == 200
    assert exact.json()["id"] == project.id
    assert response.status_code == 200
    body = response.json()
    assert body["video_project_id"] == project.id
    assert body["product_id"] == project.product_id
    assert body["marketing_strategy_id"] == project.marketing_strategy_id
    assert body["copy_matrix_id"] == project.copy_matrix_id
    assert body["input_ready"] is True
    assert body["provider"] == "Wanx"
    assert body["provider_configured"] is True
    assert body["execution_enabled"] is False
    assert body["contract_ready"] is False
    assert body["ready_for_execution"] is False
    assert body["preflight_only"] is True
    assert body["scene_count"] == 2
    assert (
        "exact_video_project_render_task_execution_contract"
        in body["missing_requirements"]
    )
    assert "uncertain_submit_recovery_contract" in body["missing_requirements"]
    assert "durable_video_artifact_storage_contract" in body["missing_requirements"]
    assert "MarketingBrief" in body["association_notice"]
    assert provider_resolutions == 0
    assert before == after == (0, 0)


def test_preflight_missing_project_returns_404(client: TestClient) -> None:
    response = client.get(preflight_path(999))
    assert response.status_code == 404


def test_preflight_missing_product_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    project = create_video_project(db_session)
    project.product_id = 999
    db_session.commit()

    response = client.get(preflight_path(project.id))

    assert response.status_code == 404


def test_preflight_rejects_cross_product_associations(
    client: TestClient,
    db_session: Session,
) -> None:
    project = create_video_project(db_session)
    other = Product(
        name="Other product",
        category="Appliance",
        description="Another product description.",
        selling_points=["Separate"],
        target_markets=["US"],
    )
    db_session.add(other)
    db_session.flush()
    project.product_id = other.id
    db_session.commit()

    response = client.get(preflight_path(project.id))

    assert response.status_code == 200
    assert response.json()["input_ready"] is False
    assert "marketing_strategy_association" in response.json()[
        "missing_requirements"
    ]
    assert "copy_matrix_association" in response.json()["missing_requirements"]


def test_preflight_reports_incomplete_project_and_blank_scene(
    client: TestClient,
    db_session: Session,
) -> None:
    project = create_video_project(db_session)
    project.title = " "
    project.scenes = [
        {
            "sequence": 1,
            "duration_seconds": 10,
            "shot_type": "\t",
            "visual_description": " ",
            "action": "\n",
            "narration": " ",
        }
    ]
    db_session.commit()

    response = client.get(preflight_path(project.id))

    assert response.status_code == 200
    body = response.json()
    assert body["input_ready"] is False
    assert "title" in body["missing_requirements"]
    assert "scene_1_schema" in body["missing_requirements"]
    assert "video_project_schema" in body["missing_requirements"]


def test_preflight_reports_empty_scenes(
    client: TestClient,
    db_session: Session,
) -> None:
    project = create_video_project(db_session)
    project.scenes = []
    db_session.commit()

    response = client.get(preflight_path(project.id))

    assert response.status_code == 200
    assert response.json()["input_ready"] is False
    assert "scenes" in response.json()["missing_requirements"]


def test_preflight_reports_safe_provider_and_execution_booleans(
    client: TestClient,
    db_session: Session,
) -> None:
    project = create_video_project(db_session)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        wanx_api_key=None,
        enable_video_render_execution=True,
    )

    response = client.get(preflight_path(project.id))

    assert response.status_code == 200
    body = response.json()
    assert body["provider_configured"] is False
    assert body["execution_enabled"] is True
    assert body["contract_ready"] is False
    assert body["ready_for_execution"] is False
    serialized = response.text.casefold()
    assert "safe-test-placeholder" not in serialized
    assert "safe-test-workspace" not in serialized
    assert "authorization" not in serialized
    assert "render_prompt" not in serialized


def test_latest_video_project_is_deterministic_and_read_only(
    client: TestClient,
    db_session: Session,
) -> None:
    first = create_video_project(db_session)
    second = VideoProject(
        product_id=first.product_id,
        marketing_strategy_id=first.marketing_strategy_id,
        copy_matrix_id=first.copy_matrix_id,
        platform=first.platform,
        title="Latest project",
        concept=first.concept,
        duration_seconds=first.duration_seconds,
        aspect_ratio=first.aspect_ratio,
        scenes=first.scenes,
        cta=first.cta,
        status=first.status,
        created_at=first.created_at + timedelta(seconds=1),
        updated_at=utc_now(),
    )
    db_session.add(second)
    db_session.commit()
    db_session.refresh(second)
    before = count_rows(db_session, VideoProject)

    response = client.get(
        f"/api/v1/products/{first.product_id}/video-projects/latest"
    )

    assert response.status_code == 200
    assert response.json()["id"] == second.id
    assert count_rows(db_session, VideoProject) == before


def test_latest_video_project_404_states(
    client: TestClient,
    db_session: Session,
) -> None:
    missing_product = client.get(
        "/api/v1/products/999/video-projects/latest"
    )
    product = Product(
        name="No video",
        category="Appliance",
        description="Product without video project.",
        selling_points=["Portable"],
        target_markets=["US"],
    )
    db_session.add(product)
    db_session.commit()
    no_project = client.get(
        f"/api/v1/products/{product.id}/video-projects/latest"
    )

    assert missing_product.status_code == 404
    assert no_project.status_code == 404
