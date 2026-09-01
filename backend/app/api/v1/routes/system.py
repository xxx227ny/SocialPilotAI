from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import WorkspaceProviderSettingsDep
from app.db.session import get_db
from app.schemas.system import SystemReadinessRead
from app.services.system_readiness_service import SystemReadinessService

router = APIRouter(prefix="/system")
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = WorkspaceProviderSettingsDep


@router.get("/readiness", response_model=SystemReadinessRead)
def get_system_readiness(
    db: DbSession,
    app_settings: SettingsDep,
) -> SystemReadinessRead:
    return SystemReadinessService(db, app_settings).get()
