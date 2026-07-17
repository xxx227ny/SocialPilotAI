from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import TextProviderDep
from app.db.session import get_db
from app.schemas.campaign import CampaignUploadResponse
from app.schemas.growth import GrowthAnalysisResponse
from app.services.campaign_service import CampaignService
from app.services.growth_analysis_service import GrowthAnalysisService

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]


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


@router.post(
    "/{product_id}/growth-analysis", response_model=GrowthAnalysisResponse
)
def analyze_product_growth(
    product_id: int, db: DbSession, provider: TextProviderDep
) -> GrowthAnalysisResponse:
    return GrowthAnalysisService(db, provider).analyze(product_id)
