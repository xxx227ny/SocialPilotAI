from dataclasses import replace

import pytest

from app.services.instagram_media_probe import (
    InstagramMediaProbeError,
    InstagramMediaSpecification,
    parse_ffprobe_payload,
    validate_instagram_reel_media,
)


def valid() -> InstagramMediaSpecification:
    return InstagramMediaSpecification(
        "mov,mp4", "h264", 30, 15, 1080, 1920, "aac", 48_000
    )


def test_ffprobe_payload_parses_exact_video_and_audio() -> None:
    parsed = parse_ffprobe_payload(
        {
            "format": {"format_name": "mov,mp4", "duration": "15"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1080,
                    "height": 1920,
                    "r_frame_rate": "30000/1000",
                },
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
            ],
        }
    )
    validate_instagram_reel_media(
        parsed, content_type="video/quicktime", size_bytes=100
    )
    assert parsed == valid()


@pytest.mark.parametrize(
    "changes",
    [
        {"container": "avi"},
        {"video_codec": "vp9"},
        {"fps": 22},
        {"fps": 61},
        {"duration_seconds": 2},
        {"duration_seconds": 901},
        {"width": 1921},
        {"audio_codec": "mp3"},
        {"audio_sample_rate": 44_100},
    ],
)
def test_each_invalid_media_contract_fails_closed(changes: dict[str, object]) -> None:
    with pytest.raises(InstagramMediaProbeError):
        validate_instagram_reel_media(
            replace(valid(), **changes), content_type="video/mp4", size_bytes=100
        )


@pytest.mark.parametrize(
    "content_type,size",
    [("video/webm", 100), ("video/mp4", 0), ("video/mp4", 1_000_000_001)],
)
def test_content_type_and_size_fail_closed(content_type: str, size: int) -> None:
    with pytest.raises(InstagramMediaProbeError):
        validate_instagram_reel_media(
            valid(), content_type=content_type, size_bytes=size
        )
