from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import CopyExecutionGateDep, TextProviderDep
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.copy import CopyMatrixSchema
from app.services.copy_generation_service import CopyGenerationService

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/{product_id}/copy", response_model=CopyMatrixSchema)
def generate_product_copy(
    product_id: int,
    db: DbSession,
    execution_gate: CopyExecutionGateDep,
    provider: TextProviderDep,
    app_settings: SettingsDep,
) -> CopyMatrixSchema:
    del execution_gate
    return CopyGenerationService(
        db, provider, app_settings
    ).generate_for_product(product_id)
