from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Product, ProductAsset
from app.schemas.product import ProductAssetCreate, ProductCreate, ProductUpdate


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, data: ProductCreate) -> Product:
        product = Product(**data.model_dump())
        self.session.add(product)
        self.session.commit()
        return self.get(product.id)  # type: ignore[return-value]

    def list(self) -> list[Product]:
        statement = (
            select(Product)
            .options(selectinload(Product.assets))
            .order_by(Product.created_at.desc())
        )
        return list(self.session.scalars(statement).all())

    def get(self, product_id: int) -> Product | None:
        statement = (
            select(Product)
            .options(selectinload(Product.assets))
            .where(Product.id == product_id)
        )
        return self.session.scalar(statement)

    def update(self, product: Product, data: ProductUpdate) -> Product:
        for field, value in data.model_dump(
            exclude_unset=True, exclude_none=True
        ).items():
            setattr(product, field, value)
        self.session.commit()
        return self.get(product.id)  # type: ignore[return-value]

    def add_asset(self, product_id: int, data: ProductAssetCreate) -> ProductAsset:
        asset = ProductAsset(product_id=product_id, **data.model_dump())
        self.session.add(asset)
        self.session.commit()
        self.session.refresh(asset)
        return asset
