from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.product import (
    ProductAssetCreate,
    ProductAssetRead,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)
from app.services.product import ProductService

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]


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
def update_product(
    product_id: int, data: ProductUpdate, db: DbSession
) -> ProductRead:
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
