"""Pydantic API schemas."""

from app.schemas.campaign import (
    CampaignMetricsSchema,
    CampaignRowSchema,
    CampaignUploadResponse,
)
from app.schemas.copy import CopyMatrixSchema, PlatformCopySchema
from app.schemas.dashboard import DashboardSnapshotSchema
from app.schemas.growth import GrowthAnalysisResponse, GrowthRecommendation
from app.schemas.marketing import MarketingTaskCreate, MarketingTaskRead
from app.schemas.product import (
    ProductAssetCreate,
    ProductAssetRead,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)
from app.schemas.strategy import MarketingStrategySchema
from app.schemas.video import (
    VideoPlanSchema,
    VideoProjectRequest,
    VideoProjectSchema,
    VideoSceneSchema,
)
from app.schemas.video_render import VideoRenderTaskCreate, VideoRenderTaskSchema
from app.schemas.video_render_artifact import (
    VideoRenderArtifactCreate,
    VideoRenderArtifactSchema,
)

__all__ = [
    "CampaignMetricsSchema",
    "CampaignRowSchema",
    "CampaignUploadResponse",
    "CopyMatrixSchema",
    "DashboardSnapshotSchema",
    "GrowthAnalysisResponse",
    "GrowthRecommendation",
    "MarketingTaskCreate",
    "MarketingTaskRead",
    "MarketingStrategySchema",
    "ProductAssetCreate",
    "ProductAssetRead",
    "ProductCreate",
    "ProductRead",
    "ProductUpdate",
    "PlatformCopySchema",
    "VideoPlanSchema",
    "VideoProjectRequest",
    "VideoProjectSchema",
    "VideoSceneSchema",
    "VideoRenderTaskCreate",
    "VideoRenderTaskSchema",
    "VideoRenderArtifactCreate",
    "VideoRenderArtifactSchema",
]
