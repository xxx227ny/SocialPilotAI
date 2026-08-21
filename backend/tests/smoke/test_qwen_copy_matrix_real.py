from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.core.config import settings
from app.models import MarketingStrategy, Product
from app.providers.live_configuration import effective_qwen_api_key
from app.providers.qwen_provider import QwenProvider
from app.schemas.copy import CopyMatrixSchema
from app.services.copy_generation_service import CopyGenerationService

pytestmark = [pytest.mark.smoke, pytest.mark.qwen_smoke]

PLATFORMS = ["TikTok", "Instagram", "Facebook", "Pinterest"]


def _new_output_path() -> Path:
    value = os.getenv("QWEN_COPY_MATRIX_OUTPUT", "").strip()
    path = Path(value)
    if not value or not path.is_absolute() or not path.parent.is_dir():
        pytest.fail("QWEN_COPY_MATRIX_OUTPUT must be in an existing absolute directory")
    if path.exists():
        pytest.fail("QWEN_COPY_MATRIX_OUTPUT must point to a new file")
    return path


def test_qwen_real_four_platform_copy_matrix() -> None:
    if not effective_qwen_api_key(settings):
        pytest.skip("Token Plan credentials are not configured")
    output_path = _new_output_path()
    product = Product(
        id=1,
        name="Fictional teal portable blender",
        category="Portable kitchen appliance",
        description="A cordless blender for fresh drinks away from home.",
        selling_points=[
            "portable design",
            "rechargeable power",
            "easy cleaning",
        ],
        target_markets=["US"],
    )
    strategy = MarketingStrategy(
        id=1,
        product_id=1,
        positioning="Fresh smoothies anywhere in seconds",
        audience_insights=["Busy commuters value convenience and easy cleanup"],
        angles=["Portable fresh-drink routine", "Rechargeable everyday convenience"],
        risks=["Do not make medical, weight-loss, or unsupported performance claims"],
        evidence=["Portable", "Rechargeable", "Easy to clean"],
    )

    provider = QwenProvider(settings)
    raw = provider.generate(CopyGenerationService._build_prompt(product, strategy))
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    parsed["product_id"] = product.id
    matrix = CopyMatrixSchema.model_validate(parsed)
    assert [copy.platform for copy in matrix.copies] == PLATFORMS
    assert len({copy.caption.casefold() for copy in matrix.copies}) == 4
    assert len({copy.hook.casefold() for copy in matrix.copies}) == 4
    assert all(copy.hashtags for copy in matrix.copies)

    output_path.write_text(
        json.dumps(
            {
                "product": product.name,
                "provider_model": settings.qwen_model,
                "copies": [copy.model_dump() for copy in matrix.copies],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "provider_calls": 1,
                "platforms": PLATFORMS,
                "caption_lengths": [len(copy.caption) for copy in matrix.copies],
            },
            sort_keys=True,
        )
    )
