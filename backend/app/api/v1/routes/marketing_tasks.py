from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.marketing import MarketingTaskCreate, MarketingTaskRead
from app.services.marketing import MarketingService

router = APIRouter(prefix="/marketing-tasks")
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "", response_model=MarketingTaskRead, status_code=status.HTTP_201_CREATED
)
def create_marketing_task(
    data: MarketingTaskCreate, db: DbSession
) -> MarketingTaskRead:
    return MarketingService(db).create(data)
