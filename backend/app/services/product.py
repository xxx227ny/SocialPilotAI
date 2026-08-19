from pathlib import Path

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import Product, ProductAsset
from app.repositories.product import ProductRepository
from app.schemas.product import ProductAssetCreate, ProductCreate, ProductUpdate
from app.services.product_asset_storage import ProductAssetStorage


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
