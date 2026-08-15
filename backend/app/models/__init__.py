"""SQLAlchemy business models."""

from app.models.batch_video import BatchVideoJob, BatchVideoVariant
from app.models.brand_kit import BrandKit, BrandKitVersion
from app.models.campaign import AdCampaign
from app.models.copy import CopyMatrix
from app.models.demo import DemoScenario
from app.models.execution import ExecutionAttempt, ExecutionJob
from app.models.marketing import MarketingBrief
from app.models.presentation_snapshot import PresentationSnapshot
from app.models.product import Product, ProductAsset
from app.models.social import OAuthSession, PublishTask, SocialAccount
from app.models.strategy import MarketingStrategy
from app.models.video import VideoProject
from app.models.video_composition import (
    VideoComposition,
    VideoCompositionArtifact,
    VideoCompositionAudioArtifact,
    VideoCompositionEnhancement,
    VideoCompositionEnhancementArtifact,
    VideoCompositionShot,
    VideoCompositionSubtitleArtifact,
)
from app.models.video_render import VideoRenderTask
from app.models.video_render_artifact import VideoRenderArtifact

__all__ = [
    "AdCampaign",
    "BrandKit",
    "BrandKitVersion",
    "BatchVideoJob",
    "BatchVideoVariant",
    "CopyMatrix",
    "DemoScenario",
    "ExecutionAttempt",
    "ExecutionJob",
    "MarketingBrief",
    "MarketingStrategy",
    "Product",
    "ProductAsset",
    "PresentationSnapshot",
    "SocialAccount",
    "OAuthSession",
    "PublishTask",
    "VideoProject",
    "VideoRenderTask",
    "VideoRenderArtifact",
    "VideoComposition",
    "VideoCompositionShot",
    "VideoCompositionArtifact",
    "VideoCompositionAudioArtifact",
    "VideoCompositionEnhancement",
    "VideoCompositionEnhancementArtifact",
    "VideoCompositionSubtitleArtifact",
]
