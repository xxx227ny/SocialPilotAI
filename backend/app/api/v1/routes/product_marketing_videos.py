from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.db.session import get_db
from app.models import BatchVideoVariant, VideoScriptVersion
from app.schemas.product_marketing_video import (
    JobSubmitRead,
    ProductImageRenderSubmitRequest,
    ProductVideoPrepareRead,
    ProductVideoPrepareRequest,
    ProductVideoSceneRead,
    ProductVideoSourceRead,
    VoiceoverSubmitRequest,
    WanxProductImageSubmitRequest,
)
from app.services.product_image_render_service import ProductImageRenderService
from app.services.video_script_project_bridge import VideoScriptProjectBridge
from app.services.voiceover_generation_service import VoiceoverGenerationService
from app.services.wanx_product_image_service import WanxProductImageService

router = APIRouter(prefix="/products/{product_id}/real-product-video")
Db = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/sources", response_model=list[ProductVideoSourceRead])
def list_product_video_sources(
    product_id: int, db: Db, settings: SettingsDep
) -> list[ProductVideoSourceRead]:
    if not settings.enable_real_product_video:
        raise AppError("Real product video execution is disabled", 503)
    variants = (
        db.query(BatchVideoVariant)
        .filter_by(product_id=product_id, status="READY_FOR_SCRIPT")
        .order_by(BatchVideoVariant.id)
        .all()
    )
    result: list[ProductVideoSourceRead] = []
    for variant in variants:
        if variant.active_script_version_id is None:
            continue
        version = db.get(VideoScriptVersion, variant.active_script_version_id)
        if (
            version is None
            or version.batch_video_variant_id != variant.id
            or version.source_type != "QWEN_GENERATED"
            or version.created_by_kind != "QWEN_PROVIDER"
            or version.provider_name != "qwen"
        ):
            continue
        result.append(
            ProductVideoSourceRead(
                variant_id=variant.id,
                script_version_id=version.id,
                platform=variant.platform,
                language=variant.language,
                content_digest=version.content_digest,
                scenes=[
                    ProductVideoSceneRead(
                        id=scene.id,
                        sequence=scene.sequence,
                        start_ms=scene.start_ms,
                        end_ms=scene.end_ms,
                        visual_description=scene.visual_description,
                        action_description=scene.action_description,
                        narration=scene.narration,
                        subtitle_draft=scene.subtitle_draft,
                    )
                    for scene in version.scenes
                ],
            )
        )
    return result


@router.post("/prepare", response_model=ProductVideoPrepareRead)
def prepare_product_video(
    product_id: int, data: ProductVideoPrepareRequest, db: Db, settings: SettingsDep
) -> ProductVideoPrepareRead:
    if not settings.enable_real_product_video:
        raise AppError("Real product video execution is disabled", 503)
    return VideoScriptProjectBridge(db).prepare(product_id, data)


@router.post(
    "/image-jobs", response_model=JobSubmitRead, status_code=status.HTTP_201_CREATED
)
def submit_product_image_job(
    product_id: int,
    data: ProductImageRenderSubmitRequest,
    db: Db,
    settings: SettingsDep,
) -> JobSubmitRead:
    return ProductImageRenderService(db, settings).enqueue(product_id, data)


@router.post(
    "/wanx-image-jobs",
    response_model=JobSubmitRead,
    status_code=status.HTTP_201_CREATED,
)
def submit_wanx_product_image_job(
    product_id: int,
    data: WanxProductImageSubmitRequest,
    db: Db,
    settings: SettingsDep,
) -> JobSubmitRead:
    return WanxProductImageService(db, settings).enqueue(product_id, data)


@router.post(
    "/voiceover-jobs", response_model=JobSubmitRead, status_code=status.HTTP_201_CREATED
)
def submit_voiceover_job(
    product_id: int,
    data: VoiceoverSubmitRequest,
    db: Db,
    settings: SettingsDep,
) -> JobSubmitRead:
    return VoiceoverGenerationService(db, settings).enqueue(product_id, data)
