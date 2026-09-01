import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.exceptions import AppError
from app.services import video_preview


def test_preview_is_low_bitrate_faststart_and_reused(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original-video-remains-immutable")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    commands = []

    def fake_encoder(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"preview-mp4")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(video_preview.subprocess, "run", fake_encoder)
    first = video_preview.video_preview_path(source, digest, "ffmpeg")
    second = video_preview.video_preview_path(source, digest, "ffmpeg")

    assert first == second
    assert first.read_bytes() == b"preview-mp4"
    assert len(commands) == 1
    assert "+faststart" in commands[0]
    assert "1200k" in commands[0]
    assert "64k" in commands[0]
    assert "fps=24" in " ".join(commands[0])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_preview_failure_preserves_original(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original-video-remains-immutable")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(
        video_preview.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1),
    )

    with pytest.raises(AppError) as error:
        video_preview.video_preview_path(source, digest, "ffmpeg")

    assert error.value.status_code == 503
    assert source.read_bytes() == b"original-video-remains-immutable"
    assert not list(tmp_path.glob(".previews/*.mp4"))


def test_preview_warmup_is_best_effort(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original-video-remains-immutable")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    calls = []

    def succeed(path, value, ffmpeg):
        calls.append((path, value, ffmpeg))
        return tmp_path / "preview.mp4"

    monkeypatch.setattr(video_preview, "video_preview_path", succeed)
    assert video_preview.warm_video_preview(source, digest, "ffmpeg") is True
    assert calls == [(source, digest, "ffmpeg")]

    def fail(path, value, ffmpeg):
        raise AppError("Preview unavailable", 503)

    monkeypatch.setattr(video_preview, "video_preview_path", fail)
    assert video_preview.warm_video_preview(source, digest, "ffmpeg") is False
    assert source.read_bytes() == b"original-video-remains-immutable"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_real_preview_encoding_is_smaller_and_faststart(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1080x1920:rate=30",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-y",
            str(source),
        ],
        check=True,
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    preview = video_preview.video_preview_path(source, digest, "ffmpeg")
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-of",
            "csv=p=0",
            str(preview),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    data = preview.read_bytes()
    assert probe.stdout.strip() == "720,1280,24/1"
    assert data.find(b"moov") < data.find(b"mdat")
    assert preview.stat().st_size < source.stat().st_size
