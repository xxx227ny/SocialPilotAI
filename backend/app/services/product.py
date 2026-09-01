from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import Product, ProductAsset
from app.repositories.product import ProductRepository
from app.schemas.product import ProductAssetCreate, ProductCreate, ProductUpdate
from app.services.product_asset_storage import ProductAssetStorage

logger = logging.getLogger(__name__)


class ProductService:
    def __init__(self, session: Session) -> None:
        self.repository = ProductRepository(session)

    def create(self, data: ProductCreate) -> Product:
        return self.repository.create(data)

    def list(self) -> list[Product]:
        return self.repository.list()

    def get(self, product_id: int) -> Product:
        product = self.repository.get(product_id)
        if product is None:
            raise AppError("Product not found", status_code=404)
        return product

    def update(self, product_id: int, data: ProductUpdate) -> Product:
        return self.repository.update(self.get(product_id), data)

    def add_asset(self, product_id: int, data: ProductAssetCreate) -> ProductAsset:
        self.get(product_id)
        return self.repository.add_asset(product_id, data)

    def upload_asset(
        self,
        product_id: int,
        *,
        file_name: str,
        content_type: str,
        content: bytes,
        storage_root: Path,
        max_bytes: int,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
        process_timeout: float = 60,
    ) -> tuple[ProductAsset, bool]:
        self.get(product_id)
        storage = ProductAssetStorage(
            storage_root,
            max_bytes,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            process_timeout=process_timeout,
        )
        normalized = storage.normalize(file_name, content_type, content)
        existing = self.repository.get_asset_by_sha(product_id, normalized.sha256)
        if existing is not None:
            return existing, True
        # Asset ownership and deletion are per product. A global content hash
        # path collides with the unique storage_identity of another product.
        # Keep existing assets immutable; namespace only newly uploaded files.
        identity = (
            f"product-images/products/{product_id}/"
            f"{normalized.sha256}.{normalized.extension}"
        )
        normalized = replace(
            normalized,
            storage_identity=identity,
            path=storage.root / identity,
        )
        created_file = storage.persist(normalized)
        asset = ProductAsset(
            product_id=product_id,
            file_name=Path(file_name).name,
            file_path=normalized.storage_identity,
            file_type=normalized.extension,
            content_type=normalized.content_type,
            size_bytes=len(normalized.content),
            sha256=normalized.sha256,
            width=normalized.width,
            height=normalized.height,
            storage_identity=normalized.storage_identity,
        )
        try:
            return self.repository.persist_asset(asset), False
        except Exception:
            self.repository.session.rollback()
            if created_file and normalized.path.exists():
                normalized.path.unlink()
            raise

    def delete_asset(
        self,
        product_id: int,
        asset_id: int,
        *,
        storage_root: Path,
        max_bytes: int,
    ) -> None:
        self.get(product_id)
        asset = self.repository.get_asset(product_id, asset_id)
        if asset is None:
            raise AppError("Product asset not found", 404)
        if self.repository.referencing_tables("product_assets", asset.id):
            raise AppError(
                "该素材已被视频任务或成片引用，不能删除；请保留历史记录。",
                409,
            )
        stored_path = self._verified_stored_path(asset, storage_root, max_bytes)
        try:
            self.repository.delete_asset(asset)
        except IntegrityError as exc:
            self.repository.session.rollback()
            raise AppError(
                "该素材已被其他任务引用，不能删除；请刷新后重试。", 409
            ) from exc
        self._remove_stored_paths([(asset.id, stored_path)])

    def delete_product(
        self,
        product_id: int,
        *,
        storage_root: Path,
        max_bytes: int,
    ) -> None:
        product = self.get(product_id)
        references = self.repository.referencing_tables(
            "products", product.id, excluded_tables={"product_assets"}
        )
        if references:
            raise AppError(
                "该商品已有营销、脚本、视频、发布或投流记录，不能删除；请保留历史记录。",
                409,
            )
        stored_paths = [
            (asset.id, self._verified_stored_path(asset, storage_root, max_bytes))
            for asset in product.assets
        ]
        try:
            self.repository.delete_product(product)
        except IntegrityError as exc:
            self.repository.session.rollback()
            raise AppError(
                "该商品已被其他业务记录引用，不能删除；请刷新后重试。", 409
            ) from exc
        self._remove_stored_paths(stored_paths)

    @staticmethod
    def _verified_stored_path(
        asset: ProductAsset, storage_root: Path, max_bytes: int
    ) -> Path | None:
        if not asset.storage_identity or not asset.sha256:
            return None
        storage = ProductAssetStorage(storage_root, max_bytes)
        try:
            return storage.resolve(asset.storage_identity, asset.sha256)
        except AppError as error:
            if error.status_code == 404:
                return None
            raise

    @staticmethod
    def _remove_stored_paths(paths: list[tuple[int, Path | None]]) -> None:
        for asset_id, path in paths:
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Product asset file cleanup failed for asset %s", asset_id
                )
