import json

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import CopyMatrix, MarketingStrategy, Product
from app.providers.base import TextGenerationProvider
from app.schemas.video import VideoPlanSchema, VideoProjectRequest
from app.services.content_studio_service import ContentStudioService


class FakeVideoPlanProvider(TextGenerationProvider):
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls = 0
        self.prompt = ""

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompt = prompt
        return json.dumps(self.result)


def add_video_sources(
    db_session: Session,
) -> tuple[Product, MarketingStrategy, CopyMatrix]:
    product = Product(
        name="Portable Blender",
        category="Appliance",
        description="A portable personal blender.",
        selling_points=["USB rechargeable"],
        target_markets=["USA"],
    )
    db_session.add(product)
    db_session.flush()
    strategy = MarketingStrategy(
        product_id=product.id,
        positioning="Healthy routines anywhere.",
        audience_insights=["Busy professionals value convenience."],
        angles=["Blend at the office"],
        risks=["Avoid health guarantees."],
        evidence=["USB rechargeable."],
    )
    db_session.add(strategy)
    db_session.flush()
    copy_matrix = CopyMatrix(
        product_id=product.id,
        marketing_strategy_id=strategy.id,
        copies=[
            {
                "platform": "TikTok",
                "hook": "Fresh drinks wherever work takes you.",
                "caption": "A quick desk-to-gym routine.",
                "hashtags": ["#PortableBlender"],
                "cta": "See how it fits your day.",
            },
            {
                "platform": "Instagram",
                "hook": "A colorful routine.",
                "caption": "Lifestyle caption.",
                "hashtags": ["#Lifestyle"],
                "cta": "Save this.",
            },
            {
                "platform": "Facebook",
                "hook": "Portable convenience.",
                "caption": "Functional value.",
                "hashtags": ["#ProductValue"],
                "cta": "Learn more.",
            },
        ],
    )
    db_session.add(copy_matrix)
    db_session.commit()
    return product, strategy, copy_matrix


def valid_plan() -> dict[str, object]:
    return {
        "title": "Blend Anywhere",
        "concept": "Follow a portable blender through a busy morning.",
        "scenes": [
            {
                "sequence": 1,
                "duration_seconds": 3,
                "shot_type": "Close-up",
                "visual_description": "Fruit drops into the blender.",
                "action": "Fast ingredient cuts.",
                "narration": "No time for a fresh drink?",
            },
            {
                "sequence": 2,
                "duration_seconds": 27,
                "shot_type": "Montage",
                "visual_description": "The blender moves from desk to gym.",
                "action": "Blend, clean, and pack.",
                "narration": "Blend your routine wherever the day goes.",
            },
        ],
        "cta": "Make fresh drinks part of your day.",
    }


def test_service_calls_provider_once_and_records_all_sources(
    db_session: Session,
) -> None:
    product, strategy, copy_matrix = add_video_sources(db_session)
    provider = FakeVideoPlanProvider(valid_plan())

    project = ContentStudioService(db_session, provider).generate_for_product(
        product.id, VideoProjectRequest()
    )

    assert provider.calls == 1
    assert project.product_id == product.id
    assert project.marketing_strategy_id == strategy.id
    assert project.copy_matrix_id == copy_matrix.id
    assert project.platform == "TikTok"
    assert project.status == "planned"
    assert '"selected_platform_copy"' in provider.prompt
    assert "video files, URLs" in provider.prompt


def test_duplicate_scene_sequence_fails_schema_validation() -> None:
    payload = valid_plan() | {
        "platform": "TikTok",
        "duration_seconds": 30,
        "aspect_ratio": "9:16",
    }
    scenes = payload["scenes"]
    assert isinstance(scenes, list)
    scenes[1]["sequence"] = 1

    with pytest.raises(ValidationError, match="sequences cannot contain duplicates"):
        VideoPlanSchema.model_validate(payload)


def test_scene_duration_total_must_match_project_duration() -> None:
    payload = valid_plan() | {
        "platform": "TikTok",
        "duration_seconds": 31,
        "aspect_ratio": "9:16",
    }

    with pytest.raises(ValidationError, match="must equal duration_seconds"):
        VideoPlanSchema.model_validate(payload)


def test_invalid_provider_plan_is_not_saved(db_session: Session) -> None:
    product, _, _ = add_video_sources(db_session)
    invalid = valid_plan()
    scenes = invalid["scenes"]
    assert isinstance(scenes, list)
    scenes[0]["duration_seconds"] = 0
    provider = FakeVideoPlanProvider(invalid)

    with pytest.raises(AppError) as error:
        ContentStudioService(db_session, provider).generate_for_product(
            product.id, VideoProjectRequest()
        )

    assert error.value.status_code == 502
    assert provider.calls == 1
