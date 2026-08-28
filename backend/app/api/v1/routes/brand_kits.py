from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.brand_kit import (
    BrandKitCreate,
    BrandKitRead,
    BrandKitVersionCreateRead,
    BrandKitVersionInput,
    BrandKitVersionRead,
    ProductBrandKitBinding,
)
from app.schemas.product import ProductRead
from app.services.brand_kit_service import BrandKitService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/brand-kits",
    response_model=BrandKitRead,
    status_code=status.HTTP_201_CREATED,
)
def create_brand_kit(data: BrandKitCreate, db: DbSession) -> BrandKitRead:
    return BrandKitService(db).create(data)


@router.get("/brand-kits", response_model=list[BrandKitRead])
def list_brand_kits(db: DbSession) -> list[BrandKitRead]:
    return BrandKitService(db).list()


@router.get("/brand-kits/{brand_kit_id}", response_model=BrandKitRead)
def get_brand_kit(brand_kit_id: int, db: DbSession) -> BrandKitRead:
    return BrandKitService(db).get(brand_kit_id)


@router.get(
    "/brand-kits/{brand_kit_id}/versions", response_model=list[BrandKitVersionRead]
)
def list_brand_kit_versions(
    brand_kit_id: int, db: DbSession
) -> list[BrandKitVersionRead]:
    return BrandKitService(db).list_versions(brand_kit_id)


@router.get(
    "/brand-kits/{brand_kit_id}/versions/{version_id}",
    response_model=BrandKitVersionRead,
)
def get_brand_kit_version(
    brand_kit_id: int, version_id: int, db: DbSession
) -> BrandKitVersionRead:
    return BrandKitService(db).get_version(brand_kit_id, version_id)


@router.delete(
    "/brand-kits/{brand_kit_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_brand_kit_version(
    brand_kit_id: int, version_id: int, db: DbSession
) -> Response:
    BrandKitService(db).delete_version(brand_kit_id, version_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/brand-kits/{brand_kit_id}/versions",
    response_model=BrandKitVersionCreateRead,
)
def create_brand_kit_version(
    brand_kit_id: int, data: BrandKitVersionInput, db: DbSession
) -> BrandKitVersionCreateRead:
    return BrandKitService(db).create_version(brand_kit_id, data)


@router.delete("/brand-kits/{brand_kit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_brand_kit(brand_kit_id: int, db: DbSession) -> Response:
    BrandKitService(db).delete(brand_kit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/products/{product_id}/brand-kit-version", response_model=ProductRead)
def bind_product_brand_kit_version(
    product_id: int, data: ProductBrandKitBinding, db: DbSession
) -> ProductRead:
    return BrandKitService(db).bind_product(product_id, data)


@router.delete("/products/{product_id}/brand-kit-version", response_model=ProductRead)
def unbind_product_brand_kit_version(product_id: int, db: DbSession) -> ProductRead:
    return BrandKitService(db).unbind_product(product_id)
