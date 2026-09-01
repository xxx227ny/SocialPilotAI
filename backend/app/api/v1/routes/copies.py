from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import (
    CopyExecutionGateDep,
    TextProviderDep,
    WorkspaceProviderSettingsDep,
)
from app.db.session import get_db
from app.schemas.copy import CopyMatrixRead, CopyMatrixSchema
from app.services.copy_generation_service import (
    CopyGenerationService,
    CopyMatrixQueryService,
)

router = APIRouter(prefix="/products")
strategy_copy_router = APIRouter(prefix="/strategies")
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = WorkspaceProviderSettingsDep


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


@strategy_copy_router.get(
    "/{strategy_id}/copy/latest", response_model=CopyMatrixRead
)
def get_latest_strategy_copy(
    strategy_id: int, db: DbSession
) -> CopyMatrixRead:
    return CopyMatrixQueryService(db).get_latest_for_strategy(strategy_id)
