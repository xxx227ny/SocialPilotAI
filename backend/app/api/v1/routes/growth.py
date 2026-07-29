from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import GrowthExecutionGateDep, TextProviderDep
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.campaign import CampaignUploadResponse
from app.schemas.growth import FeedbackContextRead, GrowthAnalysisResponse
from app.services.campaign_service import CampaignService
from app.services.feedback_context_service import FeedbackContextService
from app.services.growth_analysis_service import GrowthAnalysisService

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/{product_id}/campaigns/upload", response_model=CampaignUploadResponse
)
async def upload_campaign_csv(
    product_id: int,
    db: DbSession,
    file: Annotated[UploadFile, File(description="UTF-8 campaign CSV")],
) -> CampaignUploadResponse:
    content = await file.read()
    return CampaignService(db).import_csv(
        product_id=product_id,
        file_name=file.filename or "",
        content=content,
    )


@router.get(
    "/{product_id}/feedback-context",
    response_model=FeedbackContextRead,
)
def get_product_feedback_context(
    product_id: int,
    db: DbSession,
) -> FeedbackContextRead:
    return FeedbackContextService(db).get(product_id)


@router.post(
    "/{product_id}/growth-analysis", response_model=GrowthAnalysisResponse
)
def analyze_product_growth(
    product_id: int,
    execution_gate: GrowthExecutionGateDep,
    provider: TextProviderDep,
    db: DbSession,
    app_settings: SettingsDep,
) -> GrowthAnalysisResponse:
    del execution_gate
    return GrowthAnalysisService(
        db, provider, app_settings
    ).analyze(product_id)
