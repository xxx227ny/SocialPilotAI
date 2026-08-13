from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import Settings

MAX_FFPROBE_OUTPUT_BYTES = 64 * 1024
MAX_TIKTOK_BYTES = 4_000_000_000


class TikTokMediaProbeError(Exception):
    def __init__(self, safe_error_code: str) -> None:
        self.safe_error_code = safe_error_code
        super().__init__(safe_error_code)


@dataclass(frozen=True, slots=True)
class TikTokMediaSpecification:
    container: str
    video_codec: str
    fps: float
    duration_seconds: float
    width: int
    height: int
    audio_codec: str | None
    audio_sample_rate: int | None
    bit_rate: int

    def stable_payload(self) -> dict[str, object]:
        return asdict(self)


class TikTokMediaProbe(Protocol):
    def probe(self, path: Path) -> TikTokMediaSpecification: ...


class FFprobeTikTokMediaProbe:
    def __init__(self, settings: Settings) -> None:
        self.executable = settings.tiktok_ffprobe_path.strip()
        self.timeout = settings.tiktok_media_probe_timeout

    def available(self) -> bool:
        supplied = Path(self.executable)
        return (
            supplied.is_file()
            if supplied.is_absolute()
            else shutil.which(self.executable) is not None
        )

    def probe(self, path: Path) -> TikTokMediaSpecification:
        if not path.is_absolute() or not path.is_file():
            raise TikTokMediaProbeError("TIKTOK_MEDIA_PATH_INVALID")
        if not self.available():
            raise TikTokMediaProbeError("TIKTOK_FFPROBE_UNAVAILABLE")
        command = [
            self.executable,
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration,format_name,bit_rate:"
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
            raise TikTokMediaProbeError("TIKTOK_MEDIA_PROBE_FAILED") from None
        if (
            completed.returncode != 0
            or len(completed.stdout) > MAX_FFPROBE_OUTPUT_BYTES
        ):
            raise TikTokMediaProbeError("TIKTOK_MEDIA_PROBE_FAILED")
        try:
            payload = json.loads(completed.stdout.decode("utf-8"))
            return parse_ffprobe_payload(payload)
        except (UnicodeDecodeError, ValueError, TypeError, KeyError):
            raise TikTokMediaProbeError("TIKTOK_MEDIA_PROBE_INVALID") from None


def parse_ffprobe_payload(payload: object) -> TikTokMediaSpecification:
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("format"), dict)
        or not isinstance(payload.get("streams"), list)
    ):
        raise ValueError("invalid ffprobe payload")
    videos = [
        s
        for s in payload["streams"]
        if isinstance(s, dict) and s.get("codec_type") == "video"
    ]
    audios = [
        s
        for s in payload["streams"]
        if isinstance(s, dict) and s.get("codec_type") == "audio"
    ]
    if len(videos) != 1 or len(audios) > 1:
        raise ValueError("invalid streams")
    video, audio = videos[0], audios[0] if audios else None
    return TikTokMediaSpecification(
        container=str(payload["format"]["format_name"]).casefold(),
        video_codec=str(video["codec_name"]).casefold(),
        fps=_rate(str(video["r_frame_rate"])),
        duration_seconds=float(payload["format"]["duration"]),
        width=int(video["width"]),
        height=int(video["height"]),
        audio_codec=str(audio["codec_name"]).casefold() if audio else None,
        audio_sample_rate=int(audio["sample_rate"]) if audio else None,
        bit_rate=int(payload["format"]["bit_rate"]),
    )


def validate_tiktok_media(
    spec: TikTokMediaSpecification,
    *,
    content_type: str,
    size_bytes: int,
    max_duration_seconds: int,
) -> None:
    if content_type not in {"video/mp4", "video/quicktime"} or not set(
        spec.container.split(",")
    ).intersection({"mov", "mp4"}):
        raise TikTokMediaProbeError("TIKTOK_MEDIA_CONTAINER_UNSUPPORTED")
    if spec.video_codec not in {"h264", "hevc"}:
        raise TikTokMediaProbeError("TIKTOK_MEDIA_VIDEO_CODEC_UNSUPPORTED")
    if not 23 <= spec.fps <= 60:
        raise TikTokMediaProbeError("TIKTOK_MEDIA_FRAME_RATE_INVALID")
    if not 3 <= spec.duration_seconds <= min(max_duration_seconds, 600):
        raise TikTokMediaProbeError("TIKTOK_MEDIA_DURATION_INVALID")
    if not 0 < size_bytes <= MAX_TIKTOK_BYTES:
        raise TikTokMediaProbeError("TIKTOK_MEDIA_SIZE_INVALID")
    if not 360 <= spec.width <= 4096 or not 360 <= spec.height <= 4096:
        raise TikTokMediaProbeError("TIKTOK_MEDIA_RESOLUTION_INVALID")
    if not 1 <= spec.bit_rate <= 100_000_000:
        raise TikTokMediaProbeError("TIKTOK_MEDIA_BITRATE_INVALID")
    if spec.audio_codec is not None and spec.audio_codec not in {"aac", "mp3"}:
        raise TikTokMediaProbeError("TIKTOK_MEDIA_AUDIO_INVALID")


def _rate(value: str) -> float:
    numerator, separator, denominator = value.partition("/")
    if not separator:
        return float(value)
    divisor = float(denominator)
    if divisor == 0:
        raise ValueError("invalid frame rate")
    return float(numerator) / divisor
