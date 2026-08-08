from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import (
    CopyExecutionGateDep,
    StrategyExecutionGateDep,
    TextProviderDep,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.copy import CopyMatrixExecutionRead, CopyPreflightRead
from app.schemas.marketing import MarketingTaskCreate, MarketingTaskRead
from app.schemas.strategy import (
    MarketingStrategyExecutionRead,
    StrategyPreflightRead,
)
from app.services.copy_generation_service import CopyGenerationService
from app.services.copy_preflight import CopyPreflightService
from app.services.marketing import MarketingService
from app.services.marketing_strategy_service import MarketingStrategyService
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


@router.get("", response_model=list[MarketingTaskRead])
def list_marketing_tasks(
    product_id: int, db: DbSession
) -> list[MarketingTaskRead]:
    return MarketingService(db).list_for_product(product_id)


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


@router.get(
    "/{task_id}/strategies/{strategy_id}/copy-preflight",
    response_model=CopyPreflightRead,
)
def get_copy_preflight(
    task_id: int,
    strategy_id: int,
    db: DbSession,
    app_settings: SettingsDep,
) -> CopyPreflightRead:
    return CopyPreflightService(db, app_settings).run(task_id, strategy_id)


@router.post(
    "/{task_id}/strategies/{strategy_id}/copy",
    response_model=CopyMatrixExecutionRead,
)
def generate_marketing_task_copy(
    task_id: int,
    strategy_id: int,
    db: DbSession,
    execution_gate: CopyExecutionGateDep,
    provider: TextProviderDep,
    app_settings: SettingsDep,
) -> CopyMatrixExecutionRead:
    del execution_gate
    return CopyGenerationService(
        db, provider, app_settings
    ).generate_for_marketing_task(task_id, strategy_id)


@router.post(
    "/{task_id}/strategy", response_model=MarketingStrategyExecutionRead
)
def generate_marketing_task_strategy(
    task_id: int,
    db: DbSession,
    execution_gate: StrategyExecutionGateDep,
    provider: TextProviderDep,
    app_settings: SettingsDep,
) -> MarketingStrategyExecutionRead:
    del execution_gate
    return MarketingStrategyService(
        db, provider, app_settings
    ).generate_for_marketing_task(task_id)


@router.get("/{task_id}", response_model=MarketingTaskRead)
def get_marketing_task(task_id: int, db: DbSession) -> MarketingTaskRead:
    return MarketingService(db).get(task_id)
