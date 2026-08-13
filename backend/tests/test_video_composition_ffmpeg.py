from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.video_composition_ffmpeg import FFmpegShot, VideoCompositionFFmpeg
from app.services.video_composition_probe import (
    VideoCompositionMedia,
    VideoCompositionProbe,
    VideoCompositionProbeError,
)


def test_ffmpeg_uses_fixed_safe_contract(tmp_path: Path) -> None:
    sources = []
    for index in range(3):
        path = tmp_path / f"{index}.mp4"
        path.write_bytes(b"video")
        sources.append(FFmpegShot(path, 0, 5000))
    output = tmp_path / "out.mp4"

    def fake_run(command, **kwargs):
        output.write_bytes(b"mp4")
        assert kwargs["shell"] is False
        assert (
            "-nostdin" in command
            and "libx264" in command
            and "anullsrc=r=48000:cl=stereo" in command
        )
        assert "http" not in " ".join(command).casefold()
        return type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()

    with patch("subprocess.run", side_effect=fake_run) as run:
        VideoCompositionFFmpeg("ffmpeg", 30).render(sources, output)
    assert run.call_count == 1


def test_probe_accepts_exact_contract() -> None:
    VideoCompositionProbe.validate(
        VideoCompositionMedia(
            15000, 1080, 1920, 30, 1, "h264", "yuv420p", "aac", 48000, "mov,mp4"
        )
    )


def test_probe_rejects_duration_outside_one_frame() -> None:
    with pytest.raises(VideoCompositionProbeError):
        VideoCompositionProbe.validate(
            VideoCompositionMedia(
                15035, 1080, 1920, 30, 1, "h264", "yuv420p", "aac", 48000, "mp4"
            )
        )
