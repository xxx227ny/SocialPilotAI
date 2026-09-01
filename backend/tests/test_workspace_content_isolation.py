from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    CopyMatrix,
    MarketingStrategy,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.repositories.video_render_artifact_repository import (
    VideoRenderArtifactRepository,
)

PASSWORD = "strong-user-password"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_user_auth=True,
        allow_public_registration=True,
        user_auth_session_ttl_seconds=3600,
        user_credential_encryption_key=Fernet.generate_key().decode("ascii"),
    )


def _register(client: TestClient, email: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()


def _product(name: str) -> dict[str, object]:
    return {
        "name": name,
        "category": "Consumer Electronics",
        "description": "A complete product description for isolation testing.",
        "selling_points": ["Portable design"],
        "target_markets": ["USA"],
    }


def _marketing_task(product_id: int) -> dict[str, object]:
    return {
        "product_id": product_id,
        "audience": "Young professionals",
        "language": "English",
        "platforms": ["TikTok", "Instagram", "Facebook"],
        "tone": "Clear and practical",
        "objective": "Increase qualified awareness",
    }


def _brand_kit(name: str) -> dict[str, object]:
    return {
        "name": name,
        "version": {
            "brand_name": name,
            "positioning": "Practical growth for small teams",
            "default_language": "English",
            "brand_tone": "Clear and optimistic",
            "preferred_terms": ["Trusted"],
            "forbidden_terms": ["Guaranteed"],
            "target_regions": ["US"],
            "audience_guidelines": ["Respect audience constraints"],
            "visual_guidelines": ["Use accessible contrast"],
            "required_disclosures": ["Disclose synthetic media"],
            "claims_constraints": ["No unsupported claims"],
        },
    }


def test_strategy_copy_and_video_ids_cannot_cross_workspaces(
    client: TestClient, db_session: Session
) -> None:
    app.dependency_overrides[get_settings] = _settings
    first_account = _register(client, "content-first@example.com")
    first_product = client.post(
        "/api/v1/products", json=_product("First Workspace Product")
    ).json()
    first_task = client.post(
        "/api/v1/marketing-tasks",
        json=_marketing_task(first_product["id"]),
    ).json()
    first_kit_response = client.post(
        "/api/v1/brand-kits", json=_brand_kit("First Private Brand")
    )
    assert first_kit_response.status_code == 201
    first_kit = first_kit_response.json()

    strategy = MarketingStrategy(
        product_id=first_product["id"],
        positioning="A private workspace strategy.",
        audience_insights=["Private audience insight"],
        angles=["Private creative angle"],
        risks=["Avoid unsupported claims"],
        evidence=["Portable design"],
    )
    db_session.add(strategy)
    db_session.flush()
    copy = CopyMatrix(
        product_id=first_product["id"],
        marketing_strategy_id=strategy.id,
        copies=[
            {
                "platform": platform,
                "hook": f"{platform} private hook",
                "caption": f"{platform} private caption",
                "hashtags": ["#Private"],
                "cta": "Learn more",
            }
            for platform in ("TikTok", "Instagram", "Facebook")
        ],
    )
    db_session.add(copy)
    db_session.flush()
    video = VideoProject(
        product_id=first_product["id"],
        marketing_strategy_id=strategy.id,
        copy_matrix_id=copy.id,
        platform="TikTok",
        title="Private workspace video",
        concept="Show the product in a private workspace campaign.",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[
            {
                "sequence": 1,
                "duration_seconds": 15,
                "shot_type": "Product",
                "visual_description": "Product on a clean desk",
                "action": "Show the portable design",
                "narration": "A private workspace narration",
            }
        ],
        cta="Learn more",
        status="planned",
    )
    db_session.add(video)
    db_session.flush()
    render_task = VideoRenderTask(
        video_project_id=video.id,
        scene_sequence=1,
        status="SUCCEEDED",
        provider_name="test-provider",
        provider_task_id="private-provider-task",
        render_prompt="Private render prompt",
        duration_seconds=15,
        aspect_ratio="9:16",
        resolution="720P",
        idempotency_key="private-render-task",
    )
    db_session.add(render_task)
    db_session.flush()
    artifact = VideoRenderArtifact(
        video_render_task_id=render_task.id,
        provider_output_url=None,
        storage_path="private/video.mp4",
        artifact_metadata={
            "content_type": "video/mp4",
            "size_bytes": 12,
            "sha256": "a" * 64,
        },
    )
    db_session.add(artifact)
    db_session.commit()

    client.post("/api/v1/auth/logout")
    second_account = _register(client, "content-second@example.com")
    second_product = client.post(
        "/api/v1/products", json=_product("Second Workspace Product")
    ).json()

    assert first_account["workspace_id"] != second_account["workspace_id"]
    assert client.get("/api/v1/brand-kits").json() == []
    assert client.get(f"/api/v1/brand-kits/{first_kit['id']}").status_code == 404
    assert (
        client.post(
            "/api/v1/marketing-tasks",
            json=_marketing_task(first_product["id"]),
        ).status_code
        == 404
    )
    assert client.get(f"/api/v1/marketing-tasks/{first_task['id']}").status_code == 404
    assert (
        client.get(
            f"/api/v1/marketing-tasks/{first_task['id']}/strategies/{strategy.id}"
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/strategies/{strategy.id}/copy/latest").status_code == 404
    )
    assert client.get(f"/api/v1/video-projects/{video.id}").status_code == 404
    assert client.get(f"/api/v1/video-render-tasks/{render_task.id}").status_code == 404
    assert VideoRenderArtifactRepository(db_session).get(artifact.id) is None

    own_task = client.post(
        "/api/v1/marketing-tasks", json=_marketing_task(second_product["id"])
    )
    assert own_task.status_code == 201
    own_kit = client.post("/api/v1/brand-kits", json=_brand_kit("Second Private Brand"))
    assert own_kit.status_code == 201
    assert [item["id"] for item in client.get("/api/v1/brand-kits").json()] == [
        own_kit.json()["id"]
    ]
