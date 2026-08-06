import pytest

from app.core.config import settings
from app.providers.live_configuration import effective_qwen_api_key
from app.providers.qwen_provider import QwenProvider
from app.schemas.strategy import MarketingStrategySchema

pytestmark = [pytest.mark.smoke, pytest.mark.qwen_smoke]


def test_qwen_real_structured_response() -> None:
    if not effective_qwen_api_key(settings):
        pytest.skip("Qwen credentials are not configured")

    prompt = (
        "Analyze a portable USB rechargeable blender for the USA market. "
        "Return one JSON object with non-empty positioning, audience_insights, "
        "angles, risks, and evidence fields. The last four fields must be arrays."
    )

    raw_result = QwenProvider().generate(prompt)
    strategy = MarketingStrategySchema.model_validate_json(raw_result)

    assert strategy.positioning
    assert strategy.angles
