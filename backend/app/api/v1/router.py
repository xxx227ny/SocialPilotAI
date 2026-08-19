from fastapi import APIRouter

from app.api.v1.routes.batch_video_jobs import router as batch_video_jobs_router
from app.api.v1.routes.brand_kits import router as brand_kits_router
from app.api.v1.routes.copies import router as copies_router
from app.api.v1.routes.copies import strategy_copy_router
from app.api.v1.routes.dashboard import router as dashboard_router
from app.api.v1.routes.execution_jobs import router as execution_jobs_router
from app.api.v1.routes.growth import router as growth_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.marketing_tasks import router as marketing_tasks_router
from app.api.v1.routes.presentation_snapshots import (
    router as presentation_snapshots_router,
)
from app.api.v1.routes.product_marketing_videos import (
    router as product_marketing_videos_router,
)
from app.api.v1.routes.products import router as products_router
from app.api.v1.routes.social import router as social_router
from app.api.v1.routes.strategies import router as strategies_router
from app.api.v1.routes.system import router as system_router
from app.api.v1.routes.video_compositions import router as video_compositions_router
from app.api.v1.routes.video_renders import router as video_renders_router
from app.api.v1.routes.video_script_versions import (
    router as video_script_versions_router,
)
from app.api.v1.routes.videos import router as videos_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(system_router, tags=["system"])
api_router.include_router(products_router, tags=["products"])
api_router.include_router(product_marketing_videos_router, tags=["real-product-video"])
api_router.include_router(brand_kits_router, tags=["brand-kits"])
api_router.include_router(batch_video_jobs_router, tags=["batch-video-jobs"])
api_router.include_router(execution_jobs_router, tags=["execution-jobs"])
api_router.include_router(social_router, tags=["social-publishing"])
api_router.include_router(marketing_tasks_router, tags=["marketing-tasks"])
api_router.include_router(
    presentation_snapshots_router, tags=["presentation-snapshots"]
)
api_router.include_router(strategies_router, tags=["marketing-strategies"])
api_router.include_router(copies_router, tags=["copy-matrix"])
api_router.include_router(strategy_copy_router, tags=["copy-matrix"])
api_router.include_router(growth_router, tags=["growth-copilot"])
api_router.include_router(videos_router, tags=["content-studio"])
api_router.include_router(video_renders_router, tags=["video-render-tasks"])
api_router.include_router(video_script_versions_router, tags=["video-script-versions"])
api_router.include_router(video_compositions_router, tags=["video-compositions"])
api_router.include_router(dashboard_router, tags=["demo-dashboard"])
