from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import settings
from app.providers.live_configuration import effective_wanx_api_key
from app.providers.wanx_image_provider import WanxImageProvider

pytestmark = [pytest.mark.smoke, pytest.mark.wanx_smoke]

PROMPT = """Create one photorealistic premium ecommerce advertising image.
Vertical 9:16 composition featuring a fictional cordless portable blender on a
clean modern kitchen counter. Show the complete product clearly with realistic
materials, fresh fruit nearby, natural commercial lighting, and a coherent
teal-and-silver identity. The base must be one solid seamless uninterrupted
surface with all controls and charging hardware concealed. Do not create any
control panel, screen, display, button, dial, port, badge, or marking. Keep every
surface completely blank: no letters, numbers, labels, icons, interface text,
brand marks, logos, watermarks, or decorative writing. No split screen or collage."""


def test_wanx_real_product_image() -> None:
    if not effective_wanx_api_key(settings):
        pytest.skip("Wanx credentials are not configured")
    output_value = os.getenv("WANX_IMAGE_SMOKE_OUTPUT", "").strip()
    if not output_value:
        pytest.skip("WANX_IMAGE_SMOKE_OUTPUT is not configured")
    output = Path(output_value)
    if not output.is_absolute() or not output.parent.is_dir() or output.exists():
        pytest.fail("Wanx image smoke output path is not a new absolute file")

    generated = WanxImageProvider(settings).generate(PROMPT)

    signatures = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"RIFF")
    assert generated.content.startswith(signatures)
    output.write_bytes(generated.content)
    assert output.is_file() and output.stat().st_size == len(generated.content)
    print(
        "Wanx image smoke succeeded: "
        f"bytes={len(generated.content)}, "
        f"request_id_digest={generated.request_id_digest or 'absent'}"
    )
