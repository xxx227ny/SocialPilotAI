from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.db.session import get_db
from app.schemas.product import (
    ProductAssetCreate,
    ProductAssetRead,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)
from app.schemas.product_marketing_video import ProductAssetUploadRead
from app.services.product import ProductService
from app.services.product_asset_storage import ProductAssetStorage

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(data: ProductCreate, db: DbSession) -> ProductRead:
    return ProductService(db).create(data)


@router.get("", response_model=list[ProductRead])
def list_products(db: DbSession) -> list[ProductRead]:
    return ProductService(db).list()


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: int, db: DbSession) -> ProductRead:
    return ProductService(db).get(product_id)


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(product_id: int, data: ProductUpdate, db: DbSession) -> ProductRead:
    return ProductService(db).update(product_id, data)


@router.post(
    "/{product_id}/assets",
    response_model=ProductAssetRead,
    status_code=status.HTTP_201_CREATED,
)
def add_product_asset(
    product_id: int,
    data: ProductAssetCreate,
    db: DbSession,
) -> ProductAssetRead:
    return ProductService(db).add_asset(product_id, data)


@router.post(
    "/{product_id}/image-assets",
    response_model=ProductAssetUploadRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_product_image(
    product_id: int,
    db: DbSession,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> ProductAssetUploadRead:
    if not settings.enable_real_product_video:
        raise AppError("Real product video execution is disabled", 503)
    content = await file.read(settings.product_asset_max_bytes + 1)
    asset, reused = ProductService(db).upload_asset(
        product_id,
        file_name=file.filename or "",
        content_type=file.content_type or "",
        content=content,
        storage_root=Path(settings.product_asset_storage_root or ""),
        max_bytes=settings.product_asset_max_bytes,
        ffmpeg_path=settings.video_composition_ffmpeg_path,
        ffprobe_path=settings.video_composition_ffprobe_path,
        process_timeout=settings.video_composition_process_timeout,
    )
    result = ProductAssetUploadRead.model_validate(asset)
    return result.model_copy(update={"reused": reused})


def _resolve_product_image(
    product_id: int, asset_id: int, db: Session, settings: Settings
) -> tuple[Path, object]:
    asset = ProductService(db).repository.get_asset(product_id, asset_id)
    if asset is None or not asset.storage_identity or not asset.sha256:
        raise AppError("Product asset not found", 404)
    path = ProductAssetStorage(
        Path(settings.product_asset_storage_root or ""),
        settings.product_asset_max_bytes,
        ffmpeg_path=settings.video_composition_ffmpeg_path,
        ffprobe_path=settings.video_composition_ffprobe_path,
        process_timeout=settings.video_composition_process_timeout,
    ).resolve(asset.storage_identity, asset.sha256)
    return path, asset


@router.get("/{product_id}/image-assets/{asset_id}/content")
def get_product_image(
    product_id: int, asset_id: int, db: DbSession, settings: SettingsDep
) -> FileResponse:
    path, asset = _resolve_product_image(product_id, asset_id, db, settings)
    return FileResponse(
        path,
        media_type=asset.content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(asset.size_bytes),
        },
    )


@router.get(
    "/{product_id}/image-assets/{asset_id}", response_model=ProductAssetUploadRead
)
def get_product_image_metadata(
    product_id: int, asset_id: int, db: DbSession
) -> ProductAssetUploadRead:
    asset = ProductService(db).repository.get_asset(product_id, asset_id)
    if asset is None or not asset.sha256:
        raise AppError("Product asset not found", 404)
    return ProductAssetUploadRead.model_validate(asset)


@router.head("/{product_id}/image-assets/{asset_id}/content")
def head_product_image(
    product_id: int, asset_id: int, db: DbSession, settings: SettingsDep
) -> FileResponse:
    path, asset = _resolve_product_image(product_id, asset_id, db, settings)
    return FileResponse(
        path,
        media_type=asset.content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(asset.size_bytes),
        },
    )
