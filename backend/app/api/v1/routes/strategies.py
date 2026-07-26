from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import StrategyExecutionGateDep, TextProviderDep
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.strategy import MarketingStrategyRead
from app.services.marketing_strategy_service import (
    MarketingStrategyQueryService,
    MarketingStrategyService,
)

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/{product_id}/strategy", response_model=MarketingStrategyRead)
def generate_product_strategy(
    product_id: int,
    db: DbSession,
    execution_gate: StrategyExecutionGateDep,
    provider: TextProviderDep,
    app_settings: SettingsDep,
) -> MarketingStrategyRead:
    del execution_gate
    return MarketingStrategyService(
        db, provider, app_settings
    ).generate_for_product(product_id)


@router.get(
    "/{product_id}/strategies/latest", response_model=MarketingStrategyRead
)
def get_latest_product_strategy(
    product_id: int, db: DbSession
) -> MarketingStrategyRead:
    return MarketingStrategyQueryService(db).get_latest_for_product(product_id)
