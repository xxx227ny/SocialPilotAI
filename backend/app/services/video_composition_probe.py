from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


class VideoCompositionProbeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VideoCompositionMedia:
    duration_ms: int
    width: int
    height: int
    fps_numerator: int
    fps_denominator: int
    video_codec: str
    pixel_format: str
    audio_codec: str
    audio_sample_rate: int
    container: str


class VideoCompositionProbe:
    MAX_OUTPUT = 64 * 1024

    def __init__(self, executable: str, timeout: float) -> None:
        self.executable = executable
        self.timeout = timeout

    def inspect(self, path: Path) -> VideoCompositionMedia:
        command = [
            self.executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,sample_rate",
            "-of",
            "json",
            str(path),
        ]
        try:
            result = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise VideoCompositionProbeError("COMPOSITION_FFPROBE_FAILED") from exc
        if result.returncode or len(result.stdout) > self.MAX_OUTPUT:
            raise VideoCompositionProbeError("COMPOSITION_FFPROBE_FAILED")
        try:
            payload = json.loads(result.stdout)
            streams = payload["streams"]
            video = next(item for item in streams if item["codec_type"] == "video")
            audio = next(item for item in streams if item["codec_type"] == "audio")
            numerator, denominator = str(video["r_frame_rate"]).split("/", 1)
            return VideoCompositionMedia(
                duration_ms=round(float(payload["format"]["duration"]) * 1000),
                width=int(video["width"]),
                height=int(video["height"]),
                fps_numerator=int(numerator),
                fps_denominator=int(denominator),
                video_codec=str(video["codec_name"]).casefold(),
                pixel_format=str(video["pix_fmt"]).casefold(),
                audio_codec=str(audio["codec_name"]).casefold(),
                audio_sample_rate=int(audio["sample_rate"]),
                container=str(payload["format"]["format_name"]).casefold(),
            )
        except (
            KeyError,
            StopIteration,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise VideoCompositionProbeError("COMPOSITION_FFPROBE_INVALID") from exc

    @staticmethod
    def validate(media: VideoCompositionMedia) -> None:
        valid_container = "mp4" in media.container
        if not all(
            (
                abs(media.duration_ms - 15000) <= 34,
                media.width == 1080,
                media.height == 1920,
                media.fps_numerator == 30,
                media.fps_denominator == 1,
                media.video_codec == "h264",
                media.pixel_format == "yuv420p",
                media.audio_codec == "aac",
                media.audio_sample_rate == 48000,
                valid_container,
            )
        ):
            raise VideoCompositionProbeError("COMPOSITION_OUTPUT_CONTRACT_FAILED")
