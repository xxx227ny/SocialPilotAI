from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import TextProviderDep
from app.db.session import get_db
from app.schemas.strategy import MarketingStrategyRead
from app.services.marketing_strategy_service import (
    MarketingStrategyQueryService,
    MarketingStrategyService,
)

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/{product_id}/strategy", response_model=MarketingStrategyRead)
def generate_product_strategy(
    product_id: int, db: DbSession, provider: TextProviderDep
) -> MarketingStrategyRead:
    return MarketingStrategyService(db, provider).generate_for_product(product_id)


@router.get(
    "/{product_id}/strategies/latest", response_model=MarketingStrategyRead
)
def get_latest_product_strategy(
    product_id: int, db: DbSession
) -> MarketingStrategyRead:
    return MarketingStrategyQueryService(db).get_latest_for_product(product_id)
