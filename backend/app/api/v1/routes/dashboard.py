from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth_dependency import ProductPrincipalDep
from app.db.session import get_db
from app.repositories.demo import DemoScenarioRepository
from app.schemas.dashboard import (
    DashboardSnapshotSchema,
    WorkspaceActivitySummarySchema,
)
from app.services.dashboard_service import DashboardService
from app.services.demo_service import DemoService
from app.services.workspace_activity_summary_service import (
    WorkspaceActivitySummaryService,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/demo/prepare", response_model=DashboardSnapshotSchema)
def prepare_demo(db: DbSession) -> DashboardSnapshotSchema:
    return DemoService(db).prepare()


@router.get("/demo/snapshot", response_model=DashboardSnapshotSchema)
def get_demo_snapshot(db: DbSession) -> DashboardSnapshotSchema:
    return DemoService(db).get_existing_snapshot()


@router.get(
    "/dashboard/products/{product_id}", response_model=DashboardSnapshotSchema
)
def get_product_dashboard(
    product_id: int, db: DbSession
) -> DashboardSnapshotSchema:
    scenario = DemoScenarioRepository(db).get_by_product(product_id)
    return DashboardService(db).get_snapshot(product_id, demo_scenario=scenario)


@router.get(
    "/dashboard/workspace-summary",
    response_model=WorkspaceActivitySummarySchema,
)
def get_workspace_activity_summary(
    db: DbSession,
    principal: ProductPrincipalDep,
) -> WorkspaceActivitySummarySchema:
    return WorkspaceActivitySummaryService(db).get(principal.workspace_id)
