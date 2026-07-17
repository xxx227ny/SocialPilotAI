from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError
from app.models import (
    AdCampaign,
    CopyMatrix,
    DemoScenario,
    MarketingStrategy,
    Product,
    VideoProject,
)
from app.repositories.demo import DemoScenarioRepository
from app.schemas.copy import CopyMatrixSchema
from app.schemas.dashboard import DashboardSnapshotSchema
from app.schemas.growth import GrowthRecommendation
from app.schemas.video import VideoPlanSchema
from app.services.dashboard_service import DashboardService

DEMO_SLUG = "portable-blender-growth-loop"


class DemoService:
    """Prepare a preset scenario without importing or calling any AI provider."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.demo_repository = DemoScenarioRepository(session)

    def prepare(self) -> DashboardSnapshotSchema:
        if settings.app_environment.casefold() != "development":
            raise AppError(
                "Demo mode is only available in development", status_code=403
            )

        scenario = self.demo_repository.get_by_slug(DEMO_SLUG)
        if scenario is None:
            scenario = self._create_scenario()
        return DashboardService(self.session).get_snapshot(
            scenario.product_id, demo_scenario=scenario
        )

    def get_existing_snapshot(self) -> DashboardSnapshotSchema:
        """Read the prepared demo snapshot without creating or mutating data."""
        scenario = self.demo_repository.get_by_slug(DEMO_SLUG)
        if scenario is None:
            raise AppError(
                "Demo snapshot not found; prepare the demo first",
                status_code=404,
            )
        return DashboardService(self.session).get_snapshot(
            scenario.product_id, demo_scenario=scenario
        )

    def _create_scenario(self) -> DemoScenario:
        copy_data = CopyMatrixSchema.model_validate(
            {
                "product_id": 1,
                "copies": [
                    {
                        "platform": "TikTok",
                        "hook": "Your fresh routine now fits in one hand.",
                        "caption": "Desk, gym, or weekend trip—blend and go.",
                        "hashtags": ["#PortableBlender", "#HealthyRoutine"],
                        "cta": "See how it fits your day.",
                    },
                    {
                        "platform": "Instagram",
                        "hook": "A fresh routine, wherever the day starts.",
                        "caption": "Colorful ingredients and a clean portable setup.",
                        "hashtags": ["#MorningRoutine", "#BlendAnywhere"],
                        "cta": "Save this routine for tomorrow.",
                    },
                    {
                        "platform": "Facebook",
                        "hook": "Fresh drinks without a full-size blender.",
                        "caption": "USB charging and easy cleaning for everyday use.",
                        "hashtags": ["#PortableKitchen", "#EverydayConvenience"],
                        "cta": "Explore the portable design.",
                    },
                ],
            }
        )
        video_plan = VideoPlanSchema.model_validate(
            {
                "title": "Blend Anywhere Morning",
                "concept": "A fast day-in-the-life story from desk to gym.",
                "platform": "TikTok",
                "duration_seconds": 30,
                "aspect_ratio": "9:16",
                "scenes": [
                    {
                        "sequence": 1,
                        "duration_seconds": 3,
                        "shot_type": "Macro close-up",
                        "visual_description": "Fruit drops into a compact blender.",
                        "action": "Three rapid ingredient cuts.",
                        "narration": "No time for a fresh drink?",
                    },
                    {
                        "sequence": 2,
                        "duration_seconds": 9,
                        "shot_type": "Desk medium shot",
                        "visual_description": "The blender runs beside a laptop.",
                        "action": "Connect, blend, and lift the cup.",
                        "narration": "Blend right where your day begins.",
                    },
                    {
                        "sequence": 3,
                        "duration_seconds": 10,
                        "shot_type": "Lifestyle montage",
                        "visual_description": "Cup moves from commute to gym bag.",
                        "action": "Carry, drink, and rinse.",
                        "narration": "Portable power for routines on the move.",
                    },
                    {
                        "sequence": 4,
                        "duration_seconds": 8,
                        "shot_type": "Product hero",
                        "visual_description": (
                            "Clean product against fresh ingredients."
                        ),
                        "action": "Slow rotation into end card.",
                        "narration": "Make fresh drinks part of your day.",
                    },
                ],
                "cta": "Blend your next fresh moment.",
            }
        )
        recommendation = GrowthRecommendation(
            problems=[
                "Facebook conversion efficiency trails the short-form channels."
            ],
            recommendations=[
                "Keep the winning portable-routine hook and test a clearer demo."
            ],
            budget_suggestion=(
                "Keep total budget stable while shifting a small test share toward "
                "the stronger TikTok creative."
            ),
            creative_suggestions=[
                "Show USB charging in the first five seconds.",
                "Test a desk-to-gym UGC transition.",
            ],
        )
        try:
            product = Product(
                name="Portable Blender Demo",
                category="Portable Kitchen Appliance",
                description=(
                    "A portable personal blender for fresh drinks anywhere."
                ),
                selling_points=[
                    "Portable design",
                    "USB rechargeable",
                    "Easy cleaning",
                    "Healthy lifestyle",
                ],
                target_markets=["USA", "Canada"],
            )
            self.session.add(product)
            self.session.flush()
            strategy = MarketingStrategy(
                product_id=product.id,
                positioning=(
                    "A portable daily-routine companion for fresh drinks on the go."
                ),
                audience_insights=[
                    "Young professionals value speed and portability.",
                    "Fitness-minded shoppers respond to visible daily routines.",
                ],
                angles=["Desk-to-gym convenience", "USB-powered portability"],
                risks=["Avoid medical or weight-loss promises."],
                evidence=["Portable design", "USB rechargeable", "Easy cleaning"],
            )
            self.session.add(strategy)
            self.session.flush()
            copy_matrix = CopyMatrix(
                product_id=product.id,
                marketing_strategy_id=strategy.id,
                copies=[copy.model_dump() for copy in copy_data.copies],
            )
            self.session.add(copy_matrix)
            self.session.flush()
            video_project = VideoProject(
                product_id=product.id,
                marketing_strategy_id=strategy.id,
                copy_matrix_id=copy_matrix.id,
                platform=video_plan.platform,
                title=video_plan.title,
                concept=video_plan.concept,
                duration_seconds=video_plan.duration_seconds,
                aspect_ratio=video_plan.aspect_ratio,
                scenes=[scene.model_dump() for scene in video_plan.scenes],
                cta=video_plan.cta,
                status="planned",
            )
            self.session.add(video_project)
            self.session.flush()
            campaigns = self._campaigns(product.id)
            self.session.add_all(campaigns)
            self.session.flush()
            scenario = DemoScenario(
                slug=DEMO_SLUG,
                label="Portable Blender Growth Loop",
                source="preset_fixture",
                fixture_version=1,
                product_id=product.id,
                marketing_strategy_id=strategy.id,
                copy_matrix_id=copy_matrix.id,
                video_project_id=video_project.id,
                campaign_ids=[campaign.id for campaign in campaigns],
                growth_recommendation=recommendation.model_dump(),
            )
            self.session.add(scenario)
            self.session.commit()
            self.session.refresh(scenario)
            return scenario
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _campaigns(product_id: int) -> list[AdCampaign]:
        values = [
            ("TikTok", "UGC Launch", 120000, 6600, 396, "3168", "12672"),
            ("Instagram", "Lifestyle", 80000, 3200, 160, "1920", "6720"),
            ("Facebook", "Value Test", 50000, 1500, 60, "960", "2496"),
        ]
        return [
            AdCampaign(
                product_id=product_id,
                platform=platform,
                campaign_name=name,
                date=date(2026, 7, index),
                impressions=impressions,
                clicks=clicks,
                conversions=conversions,
                spend=Decimal(spend),
                revenue=Decimal(revenue),
            )
            for index, (
                platform,
                name,
                impressions,
                clicks,
                conversions,
                spend,
                revenue,
            ) in enumerate(values, start=1)
        ]
