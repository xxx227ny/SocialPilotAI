from __future__ import annotations

import pytest

from app.services.tiktok_media_probe import (
    MAX_TIKTOK_BYTES,
    TikTokMediaProbeError,
    TikTokMediaSpecification,
    parse_ffprobe_payload,
    validate_tiktok_media,
)


def test_parse_and_validate_tiktok_media() -> None:
    media = parse_ffprobe_payload(
        {
            "format": {
                "duration": "15.0",
                "format_name": "mov,mp4",
                "bit_rate": "8000000",
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1080,
                    "height": 1920,
                    "r_frame_rate": "30/1",
                },
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
            ],
        }
    )
    validate_tiktok_media(
        media, content_type="video/mp4", size_bytes=1024, max_duration_seconds=60
    )
    assert media.duration_seconds == 15


@pytest.mark.parametrize(
    "changes",
    [
        {"video_codec": "vp9"},
        {"fps": 61},
        {"duration_seconds": 2},
        {"width": 100},
        {"audio_codec": "opus"},
        {"bit_rate": 0},
    ],
)
def test_tiktok_media_rejects_invalid_contract(changes: dict[str, object]) -> None:
    values = dict(
        container="mp4",
        video_codec="h264",
        fps=30,
        duration_seconds=15,
        width=1080,
        height=1920,
        audio_codec="aac",
        audio_sample_rate=48000,
        bit_rate=8_000_000,
    )
    values.update(changes)
    with pytest.raises(TikTokMediaProbeError):
        validate_tiktok_media(
            TikTokMediaSpecification(**values),
            content_type="video/mp4",
            size_bytes=1024,
            max_duration_seconds=60,
        )


def test_tiktok_media_rejects_size_and_content_type() -> None:
    media = TikTokMediaSpecification(
        "mp4", "h264", 30, 15, 1080, 1920, None, None, 8_000_000
    )
    with pytest.raises(TikTokMediaProbeError):
        validate_tiktok_media(
            media,
            content_type="application/octet-stream",
            size_bytes=MAX_TIKTOK_BYTES + 1,
            max_duration_seconds=60,
        )
