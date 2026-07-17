"""Data-access repositories."""

from app.repositories.campaign import CampaignRepository
from app.repositories.copy import CopyMatrixRepository
from app.repositories.demo import DemoScenarioRepository
from app.repositories.marketing import MarketingRepository
from app.repositories.product import ProductRepository
from app.repositories.strategy import MarketingStrategyRepository
from app.repositories.video import VideoProjectRepository
from app.repositories.video_render import VideoRenderTaskRepository

__all__ = [
    "CampaignRepository",
    "CopyMatrixRepository",
    "DemoScenarioRepository",
    "MarketingRepository",
    "MarketingStrategyRepository",
    "ProductRepository",
    "VideoProjectRepository",
    "VideoRenderTaskRepository",
]
