from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import (
    GrowthExecutionGateDep,
    TextProviderDep,
    V2CopyExecutionGateDep,
    V2VideoProjectExecutionGateDep,
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
    GrowthAutomationControlRead,
    GrowthAutomationControlUpdate,
    GrowthAutomationEvaluationRequest,
    GrowthOptimizationExecutionPreflightRead,
    GrowthOptimizationExecutionRead,
    GrowthOptimizationExecutionRequest,
    GrowthOptimizationExecutionResult,
    GrowthOptimizationPlanRead,
    GrowthOptimizationPlanRequest,
    GrowthOptimizationRunActivateRead,
    GrowthOptimizationRunCreateRead,
    GrowthOptimizationRunCreateRequest,
    GrowthOptimizationRunRead,
    GrowthRecommendationPreflightRead,
)
from app.schemas.video import (
    V2VideoProjectExecutionRead,
    V2VideoProjectExecutionRequest,
    V2VideoProjectPreflightRead,
    V2VideoProjectSourceRequest,
)
from app.services.campaign_service import CampaignService
from app.services.feedback_context_service import FeedbackContextService
from app.services.growth_analysis_service import GrowthAnalysisService
from app.services.growth_automation_service import GrowthAutomationService
from app.services.growth_budget_optimizer import GrowthBudgetOptimizer
from app.services.growth_optimization_execution_service import (
    GrowthOptimizationExecutionService,
)
from app.services.growth_optimization_run_service import (
    GrowthOptimizationRunService,
)
from app.services.growth_recommendation_preflight import (
    GrowthRecommendationPreflightService,
)
from app.services.v2_copy_generation_service import V2CopyGenerationService
from app.services.v2_copy_preflight import V2CopyPreflightService
from app.services.v2_video_project_generation_service import (
    V2VideoProjectGenerationService,
)
from app.services.v2_video_project_preflight import (
    V2VideoProjectPreflightService,
)

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/{product_id}/campaigns/upload", response_model=CampaignUploadResponse)
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


@router.post("/{product_id}/growth-analysis", response_model=GrowthAnalysisResponse)
def analyze_product_growth(
    product_id: int,
    data: GrowthAnalysisRequest,
    execution_gate: GrowthExecutionGateDep,
    provider: TextProviderDep,
    db: DbSession,
    app_settings: SettingsDep,
) -> GrowthAnalysisResponse:
    del execution_gate
    return GrowthAnalysisService(db, provider, app_settings).analyze(
        product_id, data.expected_context_digest
    )


@router.get(
    "/{product_id}/growth-analysis/preflight",
    response_model=GrowthRecommendationPreflightRead,
)
def get_growth_recommendation_preflight(
    product_id: int,
    db: DbSession,
    app_settings: SettingsDep,
) -> GrowthRecommendationPreflightRead:
    return GrowthRecommendationPreflightService(db, app_settings).run(product_id)


@router.post(
    "/{product_id}/growth-optimization/plan",
    response_model=GrowthOptimizationPlanRead,
)
def plan_growth_optimization(
    product_id: int,
    data: GrowthOptimizationPlanRequest,
    db: DbSession,
) -> GrowthOptimizationPlanRead:
    return GrowthBudgetOptimizer(db).plan(product_id, data)


@router.post(
    "/{product_id}/growth-optimization/plans",
    response_model=GrowthOptimizationRunCreateRead,
)
def create_growth_optimization_plan(
    product_id: int,
    data: GrowthOptimizationRunCreateRequest,
    db: DbSession,
) -> GrowthOptimizationRunCreateRead:
    return GrowthOptimizationRunService(db).create(product_id, data)


@router.get(
    "/{product_id}/growth-optimization/plans",
    response_model=list[GrowthOptimizationRunRead],
)
def list_growth_optimization_plans(
    product_id: int,
    db: DbSession,
) -> list[GrowthOptimizationRunRead]:
    return GrowthOptimizationRunService(db).list(product_id)


@router.post(
    "/{product_id}/growth-optimization/plans/{run_id}/activate",
    response_model=GrowthOptimizationRunActivateRead,
)
def activate_growth_optimization_plan(
    product_id: int,
    run_id: int,
    db: DbSession,
) -> GrowthOptimizationRunActivateRead:
    return GrowthOptimizationRunService(db).activate(product_id, run_id)


@router.get(
    "/{product_id}/growth-optimization/plans/{run_id}/execution-preflight",
    response_model=GrowthOptimizationExecutionPreflightRead,
)
def preflight_growth_optimization_execution(
    product_id: int,
    run_id: int,
    db: DbSession,
) -> GrowthOptimizationExecutionPreflightRead:
    return GrowthOptimizationExecutionService(db).preflight(product_id, run_id)


@router.post(
    "/{product_id}/growth-optimization/plans/{run_id}/sandbox-executions",
    response_model=GrowthOptimizationExecutionResult,
)
def execute_growth_optimization_sandbox(
    product_id: int,
    run_id: int,
    data: GrowthOptimizationExecutionRequest,
    db: DbSession,
) -> GrowthOptimizationExecutionResult:
    return GrowthOptimizationExecutionService(db).execute(product_id, run_id, data)


@router.get(
    "/{product_id}/growth-optimization/executions",
    response_model=list[GrowthOptimizationExecutionRead],
)
def list_growth_optimization_executions(
    product_id: int,
    db: DbSession,
) -> list[GrowthOptimizationExecutionRead]:
    return GrowthOptimizationExecutionService(db).list(product_id)


@router.post(
    "/{product_id}/growth-optimization/executions/{execution_id}/rollback",
    response_model=GrowthOptimizationExecutionResult,
)
def rollback_growth_optimization_execution(
    product_id: int,
    execution_id: int,
    db: DbSession,
) -> GrowthOptimizationExecutionResult:
    return GrowthOptimizationExecutionService(db).rollback(product_id, execution_id)


@router.get(
    "/{product_id}/growth-optimization/automation",
    response_model=GrowthAutomationControlRead,
)
def get_growth_automation_control(
    product_id: int, db: DbSession
) -> GrowthAutomationControlRead:
    return GrowthAutomationService(db).get(product_id)


@router.put(
    "/{product_id}/growth-optimization/automation",
    response_model=GrowthAutomationControlRead,
)
def update_growth_automation_control(
    product_id: int,
    data: GrowthAutomationControlUpdate,
    db: DbSession,
) -> GrowthAutomationControlRead:
    return GrowthAutomationService(db).update(product_id, data)


@router.post(
    "/{product_id}/growth-optimization/automation/kill-switch",
    response_model=GrowthAutomationControlRead,
)
def engage_growth_automation_kill_switch(
    product_id: int, db: DbSession
) -> GrowthAutomationControlRead:
    return GrowthAutomationService(db).engage_kill_switch(product_id)


@router.post(
    "/{product_id}/growth-optimization/automation/evaluate",
    response_model=GrowthOptimizationExecutionResult,
)
def evaluate_growth_automation(
    product_id: int,
    data: GrowthAutomationEvaluationRequest,
    db: DbSession,
) -> GrowthOptimizationExecutionResult:
    return GrowthAutomationService(db).evaluate(product_id, data)


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
    return V2CopyGenerationService(db, provider, app_settings).generate(
        product_id, data
    )


@router.post(
    "/{product_id}/v2-video-project/preflight",
    response_model=V2VideoProjectPreflightRead,
)
def preflight_v2_video_project(
    product_id: int,
    data: V2VideoProjectSourceRequest,
    db: DbSession,
    app_settings: SettingsDep,
) -> V2VideoProjectPreflightRead:
    return V2VideoProjectPreflightService(db, app_settings).run(product_id, data)


@router.post(
    "/{product_id}/v2-video-project",
    response_model=V2VideoProjectExecutionRead,
)
def generate_v2_video_project(
    product_id: int,
    data: V2VideoProjectExecutionRequest,
    execution_gate: V2VideoProjectExecutionGateDep,
    provider: TextProviderDep,
    db: DbSession,
    app_settings: SettingsDep,
) -> V2VideoProjectExecutionRead:
    del execution_gate
    return V2VideoProjectGenerationService(db, provider, app_settings).generate(
        product_id, data
    )
