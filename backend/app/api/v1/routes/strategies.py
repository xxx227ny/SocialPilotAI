from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import TextProviderDep
from app.db.session import get_db
from app.schemas.strategy import MarketingStrategySchema
from app.services.marketing_strategy_service import MarketingStrategyService

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/{product_id}/strategy", response_model=MarketingStrategySchema)
def generate_product_strategy(
    product_id: int, db: DbSession, provider: TextProviderDep
) -> MarketingStrategySchema:
    return MarketingStrategyService(db, provider).generate_for_product(product_id)
