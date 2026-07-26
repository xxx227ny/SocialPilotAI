import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import CopyMatrix, MarketingStrategy, Product
from app.providers.base import TextGenerationProvider
from app.services.copy_generation_service import CopyGenerationService


class RecordingCopyProvider(TextGenerationProvider):
    def __init__(self, result: str) -> None:
        self.result = result
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.result


def enabled_settings() -> Settings:
    return Settings(_env_file=None, enable_copy_execution=True)


def add_product_and_strategy(db_session: Session) -> tuple[Product, MarketingStrategy]:
    product = Product(
        name="Portable Blender",
        category="Portable Kitchen Appliance",
        description="A portable personal blender for fresh drinks.",
        selling_points=["Portable design", "USB rechargeable"],
        target_markets=["USA", "Canada"],
    )
    db_session.add(product)
    db_session.flush()
    strategy = MarketingStrategy(
        product_id=product.id,
        positioning="Portable wellness companion for busy routines.",
        audience_insights=["Young professionals value convenience."],
        angles=["Fresh drinks anywhere"],
        risks=["Avoid unsupported health claims."],
        evidence=["Portable design and USB charging."],
    )
    db_session.add(strategy)
    db_session.commit()
    db_session.refresh(product)
    db_session.refresh(strategy)
    return product, strategy


def valid_copy_json() -> str:
    return json.dumps(
        {
            "copies": [
                {
                    "platform": "TikTok",
                    "hook": "Your smoothie routine just became portable.",
                    "caption": "POV: fresh drinks fit between meetings.",
                    "hashtags": ["#PortableBlender", "#DailyRoutine"],
                    "cta": "See how it fits your day.",
                },
                {
                    "platform": "Instagram",
                    "hook": "Fresh color, wherever the day takes you.",
                    "caption": "A clean, portable ritual for busy mornings.",
                    "hashtags": ["#HealthyLifestyle", "#OnTheGo"],
                    "cta": "Save this for your next morning reset.",
                },
                {
                    "platform": "Facebook",
                    "hook": "Blend fresh drinks without staying near an outlet.",
                    "caption": "Portable design and USB charging add convenience.",
                    "hashtags": ["#KitchenAppliance", "#PortableDesign"],
                    "cta": "Explore the product details.",
                },
            ]
        }
    )


def test_provider_is_called_once_and_matrix_is_saved(db_session: Session) -> None:
    product, strategy = add_product_and_strategy(db_session)
    provider = RecordingCopyProvider(valid_copy_json())

    result = CopyGenerationService(
        db_session, provider, enabled_settings()
    ).generate_for_product(product.id)

    assert len(provider.prompts) == 1
    assert "TikTok, Instagram, Facebook" in provider.prompts[0]
    assert result.marketing_strategy_id == strategy.id
    assert len(result.copies) == 3
    saved_count = db_session.scalar(select(func.count(CopyMatrix.id)))
    assert saved_count == 1


def test_json_is_parsed_into_three_platforms(db_session: Session) -> None:
    product, _ = add_product_and_strategy(db_session)
    provider = RecordingCopyProvider(valid_copy_json())

    result = CopyGenerationService(
        db_session, provider, enabled_settings()
    ).generate_for_product(product.id)

    assert [copy["platform"] for copy in result.copies] == [
        "TikTok",
        "Instagram",
        "Facebook",
    ]


@pytest.mark.parametrize(
    "provider_result",
    [
        "not-json",
        json.dumps(
            {
                "copies": [
                    {
                        "platform": "TikTok",
                        "hook": "",
                        "caption": "Caption",
                        "hashtags": [],
                        "cta": "CTA",
                    }
                ]
            }
        ),
    ],
)
def test_invalid_json_or_schema_is_rejected(
    db_session: Session, provider_result: str
) -> None:
    product, _ = add_product_and_strategy(db_session)
    provider = RecordingCopyProvider(provider_result)

    with pytest.raises(AppError, match="invalid copy data") as exc_info:
        CopyGenerationService(
            db_session, provider, enabled_settings()
        ).generate_for_product(product.id)

    assert exc_info.value.status_code == 502
    saved_count = db_session.scalar(select(func.count(CopyMatrix.id)))
    assert saved_count == 0


def test_strategy_is_required_before_provider_call(db_session: Session) -> None:
    product = Product(
        name="Travel Mug",
        category="Drinkware",
        selling_points=["Insulated"],
        target_markets=["USA"],
    )
    db_session.add(product)
    db_session.commit()
    provider = RecordingCopyProvider(valid_copy_json())

    with pytest.raises(AppError, match="must be generated first") as exc_info:
        CopyGenerationService(
            db_session, provider, enabled_settings()
        ).generate_for_product(product.id)

    assert exc_info.value.status_code == 409
    assert provider.prompts == []


def test_copy_execution_defaults_disabled_before_provider_call(
    db_session: Session,
) -> None:
    product, _ = add_product_and_strategy(db_session)
    provider = RecordingCopyProvider(valid_copy_json())

    with pytest.raises(AppError, match="disabled by the server") as exc_info:
        CopyGenerationService(
            db_session,
            provider,
            Settings(_env_file=None),
        ).generate_for_product(product.id)

    assert exc_info.value.status_code == 503
    assert provider.prompts == []
    assert db_session.scalar(select(func.count(CopyMatrix.id))) == 0
