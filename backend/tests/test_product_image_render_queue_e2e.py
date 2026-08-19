import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    ExecutionJob,
    Product,
    ProductAsset,
    VideoProject,
    VideoRenderTask,
)
from app.schemas.product_marketing_video import ProductImageRenderSubmitRequest
from app.services.product_image_render_service import ProductImageRenderService


def test_image_job_is_provider_free_idempotent_and_freezes_exact_asset(
    db_session: Session, tmp_path: Path
) -> None:
    product = Product(
        name="Product",
        category="Demo",
        description="A sufficiently detailed product description.",
        selling_points=["One"],
        target_markets=["US"],
    )
    db_session.add(product)
    db_session.flush()
    digest = hashlib.sha256(b"image").hexdigest()
    asset = ProductAsset(
        product_id=product.id,
        file_name="product.jpg",
        file_path=f"product-images/{digest[:2]}/{digest}.jpg",
        file_type="jpg",
        content_type="image/jpeg",
        size_bytes=5,
        sha256=digest,
        width=1080,
        height=1920,
        storage_identity=f"product-images/{digest[:2]}/{digest}.jpg",
    )
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=1,
        copy_matrix_id=1,
        platform="TikTok",
        title="Title",
        concept="Concept",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[
            {
                "sequence": 1,
                "duration_seconds": 5,
                "source_product_asset_id": 1,
                "source_product_asset_sha256": digest,
                "motion": "zoom_in",
            }
        ],
        cta="CTA",
    )
    db_session.add_all([asset, project])
    db_session.commit()
    request = ProductImageRenderSubmitRequest(
        video_project_id=project.id,
        scene_sequence=1,
        product_asset_id=asset.id,
        product_asset_sha256=digest,
        motion="zoom_in",
        input_digest="a" * 64,
    )
    settings = Settings(
        enable_real_product_video=True,
        product_asset_storage_root=str(tmp_path / "images"),
        video_artifact_storage_root=str(tmp_path / "videos"),
    )
    first = ProductImageRenderService(db_session, settings).enqueue(product.id, request)
    second = ProductImageRenderService(db_session, settings).enqueue(
        product.id, request
    )
    assert first.reused is False and second.reused is True
    assert first.job.id == second.job.id
    assert db_session.query(ExecutionJob).count() == 1
    assert db_session.query(VideoRenderTask).count() == 1
    assert first.job.max_attempts == 1
