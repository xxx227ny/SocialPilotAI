from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from app.core.config import settings
from app.providers.happyhorse_provider import HappyHorseProvider
from app.providers.live_configuration import effective_qwen_api_key
from app.providers.visual_base import (
    VisualGenerationRequest,
    VisualReferenceImage,
)
from app.services.video_artifact_storage import HttpProviderOutputFetcher

pytestmark = [pytest.mark.smoke, pytest.mark.happyhorse_smoke]

PROMPT = """Create a polished 15-second vertical product advertisement using
the supplied portable blender reference image. Preserve the exact teal-and-silver
product identity. Show only the inanimate product on a neutral studio tabletop.
Use a clean hero shot, slow product rotation, gentle cinematic camera movement,
and coherent commercial lighting. Do not show people, hands, faces, bodies, food
preparation, blades, liquids, splashes, or ingestion. No subtitles, logos,
watermarks, or generated on-screen text."""
POLL_INTERVAL_SECONDS = 15
MAX_WAIT_SECONDS = 10 * 60


def _required_new_path(name: str) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value)
    if not value or not path.is_absolute() or not path.parent.is_dir():
        pytest.fail(f"{name} must be a file in an existing absolute directory")
    if path.exists():
        pytest.fail(f"{name} must point to a new file")
    return path


def _write_state(path: Path, *, task_id: str, status: str) -> None:
    path.write_text(
        json.dumps({"provider_task_id": task_id, "status": status}, indent=2),
        encoding="utf-8",
    )


async def _run(image: bytes, state_path: Path, output_path: Path) -> None:
    provider = HappyHorseProvider(settings)
    submit_calls = 0
    original_submit = provider.submit

    async def submit_once(request: VisualGenerationRequest):
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls > 1:
            raise AssertionError("HappyHorse smoke attempted more than one submit")
        return await original_submit(request)

    provider.submit = submit_once  # type: ignore[method-assign]
    submitted = await provider.submit(
        VisualGenerationRequest(
            prompt=PROMPT,
            duration_seconds=15,
            aspect_ratio="9:16",
            resolution="720P",
            reference_images=(VisualReferenceImage(image, "image/png"),),
        )
    )
    assert submit_calls == 1
    _write_state(
        state_path,
        task_id=submitted.provider_task_id,
        status=submitted.status,
    )
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        snapshot = await provider.fetch(submitted.provider_task_id)
        assert submit_calls == 1
        _write_state(
            state_path,
            task_id=submitted.provider_task_id,
            status=snapshot.status,
        )
        if snapshot.status == "SUCCEEDED":
            assert snapshot.provider_output_url
            fetched = await HttpProviderOutputFetcher(
                max_bytes=settings.video_artifact_max_bytes,
                timeout=settings.happyhorse_timeout,
            ).fetch(snapshot.provider_output_url)
            assert fetched.content_type == "video/mp4"
            output_path.write_bytes(fetched.content)
            assert output_path.stat().st_size == len(fetched.content)
            print(
                "HappyHorse smoke succeeded: "
                f"bytes={len(fetched.content)}, submit_calls={submit_calls}"
            )
            return
        if snapshot.status in {"FAILED", "CANCELED"}:
            pytest.fail(f"HappyHorse task ended with status={snapshot.status}")
    pytest.fail("HappyHorse smoke timed out without resubmitting")


def test_happyhorse_real_product_video() -> None:
    if not effective_qwen_api_key(settings):
        pytest.skip("Token Plan credentials are not configured")
    image_path = Path(os.getenv("HAPPYHORSE_SMOKE_IMAGE", "").strip())
    if not image_path.is_absolute() or not image_path.is_file():
        pytest.fail("HAPPYHORSE_SMOKE_IMAGE must be an existing absolute file")
    state_path = _required_new_path("HAPPYHORSE_SMOKE_STATE")
    output_path = _required_new_path("HAPPYHORSE_SMOKE_OUTPUT")

    asyncio.run(_run(image_path.read_bytes(), state_path, output_path))
