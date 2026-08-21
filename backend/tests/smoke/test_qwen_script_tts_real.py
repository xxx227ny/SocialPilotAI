from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.core.config import settings
from app.providers.live_configuration import effective_qwen_api_key
from app.providers.qwen_provider import QwenProvider
from app.schemas.video_composition_enhancement import (
    SubtitleCueInput,
    SubtitleStyleInput,
)
from app.schemas.video_script_version import QwenScriptProviderOutput
from app.services.qwen_video_script_generation_service import (
    QwenVideoScriptGenerationService,
    select_timed_narration,
)
from app.services.tts_provider import QwenAudioTtsProvider
from app.services.video_composition_subtitles import render_webvtt
from app.services.voiceover_generation_service import VoiceoverGenerationService

pytestmark = [pytest.mark.smoke, pytest.mark.qwen_smoke]

SNAPSHOT = {
    "product": {
        "name": "Fictional teal portable blender",
        "category": "portable kitchen appliance",
        "description": "A cordless blender for fresh drinks away from home.",
        "selling_points": [
            "portable design",
            "rechargeable power",
            "easy cleaning",
        ],
    },
    "platform": "TikTok",
    "language": "en-US",
    "creative_angle": "Fresh fruit smoothies anywhere in seconds",
    "duration_ms": 15000,
    "aspect_ratio": "9:16",
}


def _path(name: str, *, allow_existing: bool) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value)
    if not value or not path.is_absolute() or not path.parent.is_dir():
        pytest.fail(f"{name} must be a file in an existing absolute directory")
    if path.exists() and not allow_existing:
        pytest.fail(f"{name} must point to a new file")
    return path


def _script(path: Path) -> tuple[QwenScriptProviderOutput, int]:
    if path.exists():
        return QwenScriptProviderOutput.model_validate_json(
            path.read_text(encoding="utf-8")
        ), 0
    result = QwenVideoScriptGenerationService(QwenProvider()).generate(SNAPSHOT)
    path.write_text(result.output.model_dump_json(indent=2), encoding="utf-8")
    return result.output, 1


def _validate_timeline(script: QwenScriptProviderOutput) -> None:
    scenes = sorted(script.scenes, key=lambda item: item.sequence)
    assert scenes[0].start_ms == 0 and scenes[-1].end_ms == 15000
    assert [scene.sequence for scene in scenes] == list(range(1, len(scenes) + 1))
    assert all(
        current.end_ms == following.start_ms
        for current, following in zip(scenes, scenes[1:], strict=False)
    )


def test_qwen_real_script_tts_and_subtitles() -> None:
    if not effective_qwen_api_key(settings):
        pytest.skip("Token Plan credentials are not configured")
    script_path = _path("QWEN_DEMO_SCRIPT_OUTPUT", allow_existing=True)
    raw_wav_path = _path("QWEN_DEMO_RAW_WAV_OUTPUT", allow_existing=True)
    wav_path = _path("QWEN_DEMO_WAV_OUTPUT", allow_existing=False)
    vtt_path = _path("QWEN_DEMO_VTT_OUTPUT", allow_existing=False)

    script, script_calls = _script(script_path)
    _validate_timeline(script)
    narration = select_timed_narration(script)
    assert len(narration.split()) <= 32

    if raw_wav_path.exists():
        raw_wav = raw_wav_path.read_bytes()
        tts_calls = 0
    else:
        raw_wav = QwenAudioTtsProvider(settings).generate(
            text=narration,
            language="en-US",
            voice=settings.qwen_tts_voice,
            rate=1.0,
        )
        raw_wav_path.write_bytes(raw_wav)
        tts_calls = 1
    normalized, natural_duration_ms, duration_ms = (
        VoiceoverGenerationService._normalize_wav(raw_wav, 15000)
    )
    assert duration_ms == 15000 and natural_duration_ms <= duration_ms
    wav_path.write_bytes(normalized)

    cues = [
        SubtitleCueInput(
            sequence=scene.sequence,
            start_ms=scene.start_ms,
            end_ms=scene.end_ms,
            text=scene.subtitle_draft,
        )
        for scene in script.scenes
    ]
    vtt_path.write_bytes(render_webvtt(cues, SubtitleStyleInput()))
    print(
        json.dumps(
            {
                "script_calls": script_calls,
                "tts_calls": tts_calls,
                "scene_count": len(script.scenes),
                "narration_words": len(narration.split()),
                "natural_duration_ms": natural_duration_ms,
                "normalized_duration_ms": duration_ms,
            },
            sort_keys=True,
        )
    )
