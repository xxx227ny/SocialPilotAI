from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import Product, ProductAsset
from app.repositories.product import ProductRepository
from app.schemas.product import ProductAssetCreate, ProductCreate, ProductUpdate


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

    def add_asset(
        self, product_id: int, data: ProductAssetCreate
    ) -> ProductAsset:
        self.get(product_id)
        return self.repository.add_asset(product_id, data)
