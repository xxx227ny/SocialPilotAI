from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import Settings

MAX_FFPROBE_OUTPUT_BYTES = 64 * 1024
MAX_INSTAGRAM_REEL_BYTES = 1_000_000_000


class InstagramMediaProbeError(Exception):
    def __init__(self, safe_error_code: str) -> None:
        self.safe_error_code = safe_error_code
        super().__init__(safe_error_code)


@dataclass(frozen=True, slots=True)
class InstagramMediaSpecification:
    container: str
    video_codec: str
    fps: float
    duration_seconds: float
    width: int
    height: int
    audio_codec: str | None
    audio_sample_rate: int | None

    def stable_payload(self) -> dict[str, object]:
        return asdict(self)


class InstagramMediaProbe(Protocol):
    def probe(self, path: Path) -> InstagramMediaSpecification: ...


class FFprobeInstagramMediaProbe:
    def __init__(self, settings: Settings) -> None:
        self.executable = settings.instagram_ffprobe_path.strip()
        self.timeout = settings.instagram_media_probe_timeout

    def available(self) -> bool:
        return instagram_media_probe_available(self.executable)

    def probe(self, path: Path) -> InstagramMediaSpecification:
        if not path.is_absolute() or not path.is_file():
            raise InstagramMediaProbeError("INSTAGRAM_MEDIA_PATH_INVALID")
        if not self.available():
            raise InstagramMediaProbeError("INSTAGRAM_FFPROBE_UNAVAILABLE")
        command = [
            self.executable,
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration,format_name:"
                "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate"
            ),
            "-of",
            "json",
            str(path),
        ]
        try:
            completed = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                check=False,
                timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise InstagramMediaProbeError("INSTAGRAM_MEDIA_PROBE_FAILED") from None
        if (
            completed.returncode != 0
            or len(completed.stdout) > MAX_FFPROBE_OUTPUT_BYTES
        ):
            raise InstagramMediaProbeError("INSTAGRAM_MEDIA_PROBE_FAILED")
        try:
            payload = json.loads(completed.stdout.decode("utf-8"))
            return parse_ffprobe_payload(payload)
        except (UnicodeDecodeError, ValueError, TypeError, KeyError):
            raise InstagramMediaProbeError("INSTAGRAM_MEDIA_PROBE_INVALID") from None


def instagram_media_probe_available(executable: str) -> bool:
    value = executable.strip()
    if not value:
        return False
    supplied = Path(value)
    if supplied.is_absolute():
        return supplied.is_file()
    return shutil.which(value) is not None


def parse_ffprobe_payload(payload: object) -> InstagramMediaSpecification:
    if not isinstance(payload, dict):
        raise ValueError("invalid ffprobe payload")
    format_payload = payload.get("format")
    streams = payload.get("streams")
    if not isinstance(format_payload, dict) or not isinstance(streams, list):
        raise ValueError("invalid ffprobe payload")
    video_streams = [
        stream
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "video"
    ]
    audio_streams = [
        stream
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    ]
    if len(video_streams) != 1 or len(audio_streams) > 1:
        raise ValueError("invalid stream count")
    video = video_streams[0]
    audio = audio_streams[0] if audio_streams else None
    return InstagramMediaSpecification(
        container=str(format_payload["format_name"]).casefold(),
        video_codec=str(video["codec_name"]).casefold(),
        fps=_rate(str(video["r_frame_rate"])),
        duration_seconds=float(format_payload["duration"]),
        width=int(video["width"]),
        height=int(video["height"]),
        audio_codec=(str(audio["codec_name"]).casefold() if audio else None),
        audio_sample_rate=(int(audio["sample_rate"]) if audio else None),
    )


def validate_instagram_reel_media(
    specification: InstagramMediaSpecification,
    *,
    content_type: str,
    size_bytes: int,
) -> None:
    if content_type not in {"video/mp4", "video/quicktime"}:
        raise InstagramMediaProbeError("INSTAGRAM_MEDIA_CONTAINER_UNSUPPORTED")
    formats = set(specification.container.split(","))
    if not formats.intersection({"mov", "mp4"}):
        raise InstagramMediaProbeError("INSTAGRAM_MEDIA_CONTAINER_UNSUPPORTED")
    if specification.video_codec not in {"h264", "hevc"}:
        raise InstagramMediaProbeError("INSTAGRAM_MEDIA_VIDEO_CODEC_UNSUPPORTED")
    if not 23 <= specification.fps <= 60:
        raise InstagramMediaProbeError("INSTAGRAM_MEDIA_FRAME_RATE_INVALID")
    if not 3 <= specification.duration_seconds <= 900:
        raise InstagramMediaProbeError("INSTAGRAM_MEDIA_DURATION_INVALID")
    if not 0 < size_bytes <= MAX_INSTAGRAM_REEL_BYTES:
        raise InstagramMediaProbeError("INSTAGRAM_MEDIA_SIZE_INVALID")
    if not 0 < specification.width <= 1920 or specification.height <= 0:
        raise InstagramMediaProbeError("INSTAGRAM_MEDIA_RESOLUTION_INVALID")
    if specification.audio_codec is not None and (
        specification.audio_codec != "aac" or specification.audio_sample_rate != 48_000
    ):
        raise InstagramMediaProbeError("INSTAGRAM_MEDIA_AUDIO_INVALID")


def _rate(value: str) -> float:
    numerator, separator, denominator = value.partition("/")
    if not separator:
        return float(value)
    divisor = float(denominator)
    if divisor == 0:
        raise ValueError("invalid frame rate")
    return float(numerator) / divisor
