from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import TextProviderDep
from app.db.session import get_db
from app.schemas.copy import CopyMatrixSchema
from app.services.copy_generation_service import CopyGenerationService

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/{product_id}/copy", response_model=CopyMatrixSchema)
def generate_product_copy(
    product_id: int, db: DbSession, provider: TextProviderDep
) -> CopyMatrixSchema:
    return CopyGenerationService(db, provider).generate_for_product(product_id)
