import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    CopyMatrix,
    MarketingStrategy,
    Product,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderModelError,
    ProviderQuotaError,
    TextGenerationProvider,
)
from app.schemas.strategy import MarketingStrategyRead, MarketingStrategySchema
from app.services.marketing_strategy_service import MarketingStrategyService

STRATEGY_LIST_FIELDS = (
    "audience_insights",
    "angles",
    "risks",
    "evidence",
)


class RecordingProvider(TextGenerationProvider):
    def __init__(self, result: str) -> None:
        self.result = result
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.result


class RaisingProvider(TextGenerationProvider):
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, prompt: str) -> str:
        del prompt
        raise self.error


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


def strategy_schema_payload(
    schema_type: type[MarketingStrategySchema],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "positioning": "Positioning",
        "audience_insights": ["Audience"],
        "angles": ["Angle"],
        "risks": ["Risk"],
        "evidence": ["Evidence"],
    }
    if schema_type is MarketingStrategyRead:
        payload.update(
            id=1,
            product_id=1,
            created_at=datetime(2026, 7, 24, tzinfo=UTC),
        )
    return payload


@pytest.mark.parametrize(
    "schema_type", [MarketingStrategySchema, MarketingStrategyRead]
)
@pytest.mark.parametrize("field", STRATEGY_LIST_FIELDS)
@pytest.mark.parametrize("blank_item", ["   ", "\t\n"])
def test_strategy_schemas_reject_blank_list_items(
    schema_type: type[MarketingStrategySchema],
    field: str,
    blank_item: str,
) -> None:
    payload = strategy_schema_payload(schema_type)
    payload[field] = [blank_item]

    with pytest.raises(ValidationError, match="empty values"):
        schema_type.model_validate(payload)


@pytest.mark.parametrize(
    "schema_type", [MarketingStrategySchema, MarketingStrategyRead]
)
@pytest.mark.parametrize("field", STRATEGY_LIST_FIELDS)
def test_strategy_schemas_trim_valid_list_items(
    schema_type: type[MarketingStrategySchema], field: str
) -> None:
    payload = strategy_schema_payload(schema_type)
    payload[field] = [" \tTrimmed value\n "]

    strategy = schema_type.model_validate(payload)

    assert getattr(strategy, field) == ["Trimmed value"]


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
    for model in (
        CopyMatrix,
        VideoProject,
        VideoRenderTask,
        VideoRenderArtifact,
    ):
        assert db_session.scalar(select(func.count(model.id))) == 0


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
    for model in (
        CopyMatrix,
        VideoProject,
        VideoRenderTask,
        VideoRenderArtifact,
    ):
        assert db_session.scalar(select(func.count(model.id))) == 0


@pytest.mark.parametrize("field", STRATEGY_LIST_FIELDS)
def test_provider_blank_list_item_is_rejected_without_writes(
    db_session: Session, field: str
) -> None:
    product = add_product(db_session)
    payload = strategy_schema_payload(MarketingStrategySchema)
    payload[field] = [" \t\n "]
    provider = RecordingProvider(json.dumps(payload))

    with pytest.raises(AppError, match="invalid strategy data") as exc_info:
        MarketingStrategyService(db_session, provider).generate_for_product(
            product.id
        )

    assert exc_info.value.status_code == 502
    for model in (
        MarketingStrategy,
        CopyMatrix,
        VideoProject,
        VideoRenderTask,
        VideoRenderArtifact,
    ):
        assert db_session.scalar(select(func.count(model.id))) == 0


@pytest.mark.parametrize(
    ("provider_error", "expected_status", "expected_message"),
    [
        (ProviderAuthenticationError("secret detail"), 502, "authentication"),
        (ProviderQuotaError("secret detail"), 429, "quota or rate limit"),
        (ProviderConnectionError("secret detail"), 503, "unavailable"),
        (ProviderModelError("secret detail"), 502, "generation failed"),
    ],
)
def test_provider_errors_are_safe_and_create_nothing(
    db_session: Session,
    provider_error: Exception,
    expected_status: int,
    expected_message: str,
) -> None:
    product = add_product(db_session)

    with pytest.raises(AppError) as exc_info:
        MarketingStrategyService(
            db_session, RaisingProvider(provider_error)
        ).generate_for_product(product.id)

    assert exc_info.value.status_code == expected_status
    assert expected_message in exc_info.value.message
    assert "secret detail" not in exc_info.value.message
    for model in (
        MarketingStrategy,
        CopyMatrix,
        VideoProject,
        VideoRenderTask,
        VideoRenderArtifact,
    ):
        assert db_session.scalar(select(func.count(model.id))) == 0
