from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.marketing import MarketingTaskCreate, MarketingTaskRead
from app.schemas.strategy import StrategyPreflightRead
from app.services.marketing import MarketingService
from app.services.strategy_preflight import StrategyPreflightService

router = APIRouter(prefix="/marketing-tasks")
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "", response_model=MarketingTaskRead, status_code=status.HTTP_201_CREATED
)
def create_marketing_task(
    data: MarketingTaskCreate, db: DbSession
) -> MarketingTaskRead:
    return MarketingService(db).create(data)


@router.get("/latest", response_model=MarketingTaskRead | None)
def get_latest_marketing_task(
    product_id: int, db: DbSession
) -> MarketingTaskRead | None:
    return MarketingService(db).get_latest_for_product(product_id)


@router.get("/{task_id}/strategy-preflight", response_model=StrategyPreflightRead)
def get_strategy_preflight(
    task_id: int, db: DbSession, app_settings: SettingsDep
) -> StrategyPreflightRead:
    return StrategyPreflightService(db, app_settings).run(task_id)


@router.get("/{task_id}", response_model=MarketingTaskRead)
def get_marketing_task(task_id: int, db: DbSession) -> MarketingTaskRead:
    return MarketingService(db).get(task_id)
