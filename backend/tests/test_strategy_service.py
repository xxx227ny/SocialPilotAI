import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import MarketingStrategy, Product
from app.providers.base import TextGenerationProvider
from app.services.marketing_strategy_service import MarketingStrategyService


class RecordingProvider(TextGenerationProvider):
    def __init__(self, result: str) -> None:
        self.result = result
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.result


def add_product(db_session: Session) -> Product:
    product = Product(
        name="Portable Blender",
        category="Portable Kitchen Appliance",
        description="A portable personal blender for fresh drinks.",
        selling_points=["Portable design", "USB rechargeable"],
        target_markets=["USA", "Canada"],
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def valid_strategy_json() -> str:
    return json.dumps(
        {
            "positioning": "Portable wellness companion for busy routines.",
            "audience_insights": ["Busy professionals value convenience."],
            "angles": ["Fresh drinks anywhere"],
            "risks": ["Avoid unsupported health claims."],
            "evidence": ["The product is portable and USB rechargeable."],
        }
    )


def test_provider_is_called_and_strategy_is_saved(db_session: Session) -> None:
    product = add_product(db_session)
    provider = RecordingProvider(valid_strategy_json())

    result = MarketingStrategyService(db_session, provider).generate_for_product(
        product.id
    )

    assert len(provider.prompts) == 1
    assert "Portable Blender" in provider.prompts[0]
    assert result.product_id == product.id
    assert result.positioning.startswith("Portable wellness")
    saved_count = db_session.scalar(select(func.count(MarketingStrategy.id)))
    assert saved_count == 1


def test_valid_json_is_parsed_into_schema(db_session: Session) -> None:
    product = add_product(db_session)
    provider = RecordingProvider(valid_strategy_json())

    result = MarketingStrategyService(db_session, provider).generate_for_product(
        product.id
    )

    assert result.angles == ["Fresh drinks anywhere"]
    assert result.evidence == [
        "The product is portable and USB rechargeable."
    ]


@pytest.mark.parametrize(
    "provider_result",
    [
        "not-json",
        json.dumps(
            {
                "positioning": "",
                "audience_insights": [],
                "angles": ["Convenience"],
                "risks": ["Claims"],
                "evidence": ["Portable"],
            }
        ),
    ],
)
def test_invalid_json_or_schema_is_rejected(
    db_session: Session, provider_result: str
) -> None:
    product = add_product(db_session)
    provider = RecordingProvider(provider_result)

    with pytest.raises(AppError, match="invalid strategy data") as exc_info:
        MarketingStrategyService(db_session, provider).generate_for_product(
            product.id
        )

    assert exc_info.value.status_code == 502
    saved_count = db_session.scalar(select(func.count(MarketingStrategy.id)))
    assert saved_count == 0
