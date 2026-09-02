from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.campaign import CampaignMetricsSchema
from app.schemas.copy import PlatformCopySchema
from app.schemas.growth import GrowthRecommendation
from app.schemas.product import ProductRead
from app.schemas.video import VideoProjectSchema

PipelineStatus = Literal["complete", "partial", "missing"]


class DashboardStrategySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    positioning: str
    audience_insights: list[str]
    angles: list[str]
    risks: list[str]
    evidence: list[str]
    created_at: datetime


class DashboardCopyMatrixSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    marketing_strategy_id: int
    copies: list[PlatformCopySchema]
    created_at: datetime


class PlatformMetricsSchema(BaseModel):
    platform: str
    metrics: CampaignMetricsSchema


class DashboardGrowthSchema(BaseModel):
    status: PipelineStatus
    metrics: CampaignMetricsSchema | None
    platform_metrics: list[PlatformMetricsSchema] = Field(default_factory=list)
    recommendation: GrowthRecommendation | None


class PipelineStepSchema(BaseModel):
    key: Literal["product", "strategy", "copy", "video", "growth"]
    label: str
    status: PipelineStatus
    source_id: int | None


class DemoMetadataSchema(BaseModel):
    slug: str
    label: str
    source: Literal["preset_fixture"]
    fixture_version: int
    badge: Literal["Demo Snapshot"] = "Demo Snapshot"
    ai_calls: Literal[0] = 0
    notice: Literal["使用预置演示数据"] = "使用预置演示数据"


class DashboardSnapshotSchema(BaseModel):
    data_source: Literal["stored_records", "demo_snapshot"]
    demo: DemoMetadataSchema | None
    product: ProductRead
    strategy: DashboardStrategySchema | None
    copy_matrix: DashboardCopyMatrixSchema | None
    video_project: VideoProjectSchema | None
    growth: DashboardGrowthSchema
    pipeline: list[PipelineStepSchema]


class WorkspaceActivitySummarySchema(BaseModel):
    """Read-only, current-workspace activity totals used by onboarding."""

    data_scope: Literal["current_workspace"] = "current_workspace"
    ai_calls: Literal[0] = 0
    api_key_configured: bool
    api_key_verified: bool
    product_count: int = Field(ge=0)
    product_asset_count: int = Field(ge=0)
    product_asset_storage_bytes: int = Field(ge=0)
    product_asset_storage_limit_bytes: int = Field(gt=0)
    strategy_count: int = Field(ge=0)
    copy_matrix_count: int = Field(ge=0)
    video_project_count: int = Field(ge=0)
    video_artifact_count: int = Field(ge=0)
    active_job_count: int = Field(ge=0)
    attention_job_count: int = Field(ge=0)
