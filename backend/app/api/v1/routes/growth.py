from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import (
    GrowthExecutionGateDep,
    TextProviderDep,
    V2CopyExecutionGateDep,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.campaign import CampaignUploadResponse
from app.schemas.copy import (
    V2CopyExecutionRead,
    V2CopyExecutionRequest,
    V2CopyPreflightRead,
    V2CopySourceRequest,
)
from app.schemas.growth import (
    FeedbackContextRead,
    GrowthAnalysisRequest,
    GrowthAnalysisResponse,
    GrowthRecommendationPreflightRead,
)
from app.services.campaign_service import CampaignService
from app.services.feedback_context_service import FeedbackContextService
from app.services.growth_analysis_service import GrowthAnalysisService
from app.services.growth_recommendation_preflight import (
    GrowthRecommendationPreflightService,
)
from app.services.v2_copy_generation_service import V2CopyGenerationService
from app.services.v2_copy_preflight import V2CopyPreflightService

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
    data: GrowthAnalysisRequest,
    execution_gate: GrowthExecutionGateDep,
    provider: TextProviderDep,
    db: DbSession,
    app_settings: SettingsDep,
) -> GrowthAnalysisResponse:
    del execution_gate
    return GrowthAnalysisService(
        db, provider, app_settings
    ).analyze(product_id, data.expected_context_digest)


@router.get(
    "/{product_id}/growth-analysis/preflight",
    response_model=GrowthRecommendationPreflightRead,
)
def get_growth_recommendation_preflight(
    product_id: int,
    db: DbSession,
    app_settings: SettingsDep,
) -> GrowthRecommendationPreflightRead:
    return GrowthRecommendationPreflightService(
        db, app_settings
    ).run(product_id)


@router.post(
    "/{product_id}/v2-copy/preflight",
    response_model=V2CopyPreflightRead,
)
def preflight_v2_copy(
    product_id: int,
    data: V2CopySourceRequest,
    db: DbSession,
    app_settings: SettingsDep,
) -> V2CopyPreflightRead:
    return V2CopyPreflightService(db, app_settings).run(product_id, data)


@router.post(
    "/{product_id}/v2-copy",
    response_model=V2CopyExecutionRead,
)
def generate_v2_copy(
    product_id: int,
    data: V2CopyExecutionRequest,
    execution_gate: V2CopyExecutionGateDep,
    provider: TextProviderDep,
    db: DbSession,
    app_settings: SettingsDep,
) -> V2CopyExecutionRead:
    del execution_gate
    return V2CopyGenerationService(
        db, provider, app_settings
    ).generate(product_id, data)
