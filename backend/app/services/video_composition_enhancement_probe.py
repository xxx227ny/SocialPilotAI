from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class VideoCompositionEnhancementProbeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EnhancementMedia:
    duration_ms: int
    width: int
    height: int
    fps_numerator: int
    fps_denominator: int
    video_codec: str
    video_profile: str
    pixel_format: str
    audio_codec: str
    audio_profile: str
    audio_sample_rate: int
    audio_channels: int
    container: str
    measured_lufs_milli: int
    measured_true_peak_millidb: int
    audio_video_sync_offset_ms: int
    longest_black_segment_ms: int


class VideoCompositionEnhancementProbe:
    MAX_OUTPUT = 128 * 1024

    def __init__(self, ffprobe: str, ffmpeg: str, timeout: float) -> None:
        self.ffprobe = ffprobe
        self.ffmpeg = ffmpeg
        self.timeout = timeout

    def inspect(self, path: Path) -> EnhancementMedia:
        probe = self._run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration,format_name:stream=codec_type,codec_name,profile,width,"
                "height,r_frame_rate,avg_frame_rate,pix_fmt,sample_rate,channels,"
                "start_time",
                "-of",
                "json",
                str(path),
            ]
        )
        loudness = self._run(
            [
                self.ffmpeg,
                "-nostdin",
                "-i",
                str(path),
                "-af",
                "ebur128=peak=true",
                "-f",
                "null",
                "-",
            ],
            include_stderr=True,
        )
        black_detection = self._run(
            [
                self.ffmpeg,
                "-nostdin",
                "-i",
                str(path),
                "-vf",
                "blackdetect=d=0.034:pix_th=0.10",
                "-an",
                "-f",
                "null",
                "-",
            ],
            include_stderr=True,
        )
        try:
            payload = json.loads(probe)
            video = next(
                item for item in payload["streams"] if item["codec_type"] == "video"
            )
            audio = next(
                item for item in payload["streams"] if item["codec_type"] == "audio"
            )
            numerator, denominator = video["avg_frame_rate"].split("/", 1)
            integrated = [
                float(value) for value in re.findall(r"I:\s*(-?[0-9.]+) LUFS", loudness)
            ][-1]
            peak = [
                float(value)
                for value in re.findall(r"Peak:\s*(-?[0-9.]+) dBFS", loudness)
            ][-1]
            video_start = float(video.get("start_time", 0) or 0)
            audio_start = float(audio.get("start_time", 0) or 0)
            black_durations = [
                float(value)
                for value in re.findall(r"black_duration:([0-9.]+)", black_detection)
            ]
            return EnhancementMedia(
                duration_ms=round(float(payload["format"]["duration"]) * 1000),
                width=int(video["width"]),
                height=int(video["height"]),
                fps_numerator=int(numerator),
                fps_denominator=int(denominator),
                video_codec=str(video["codec_name"]).casefold(),
                video_profile=str(video.get("profile", "")).casefold(),
                pixel_format=str(video["pix_fmt"]).casefold(),
                audio_codec=str(audio["codec_name"]).casefold(),
                audio_profile=str(audio.get("profile", "")).casefold(),
                audio_sample_rate=int(audio["sample_rate"]),
                audio_channels=int(audio["channels"]),
                container=str(payload["format"]["format_name"]).casefold(),
                measured_lufs_milli=round(integrated * 1000),
                measured_true_peak_millidb=round(peak * 1000),
                audio_video_sync_offset_ms=round(abs(video_start - audio_start) * 1000),
                longest_black_segment_ms=round(
                    max(black_durations, default=0.0) * 1000
                ),
            )
        except (
            KeyError,
            StopIteration,
            ValueError,
            IndexError,
            json.JSONDecodeError,
        ) as exc:
            raise VideoCompositionEnhancementProbeError(
                "ENHANCEMENT_QA_INVALID"
            ) from exc

    def validate(
        self, media: EnhancementMedia, target_lufs: int, true_peak: int
    ) -> None:
        checks = (
            ("duration", abs(media.duration_ms - 15000) <= 34),
            ("dimensions", media.width == 1080 and media.height == 1920),
            (
                "frame_rate",
                media.fps_numerator == 30 and media.fps_denominator == 1,
            ),
            ("video_codec", media.video_codec == "h264"),
            ("video_profile", "high" in media.video_profile),
            ("pixel_format", media.pixel_format == "yuv420p"),
            ("audio_codec", media.audio_codec == "aac"),
            ("audio_profile", "lc" in media.audio_profile),
            ("audio_sample_rate", media.audio_sample_rate == 48000),
            ("audio_channels", media.audio_channels == 2),
            ("container", "mp4" in media.container),
            ("audio_non_silent", media.measured_lufs_milli > -60000),
            (
                "integrated_loudness",
                abs(media.measured_lufs_milli - target_lufs) <= 1500,
            ),
            (
                "true_peak",
                media.measured_true_peak_millidb <= true_peak + 300,
            ),
            ("sync", media.audio_video_sync_offset_ms <= 34),
            ("black_segment", media.longest_black_segment_ms <= 34),
        )
        failed = next((name for name, passed in checks if not passed), None)
        if failed is not None:
            raise VideoCompositionEnhancementProbeError(
                f"ENHANCEMENT_OUTPUT_CONTRACT_FAILED:{failed}"
            )

    def _run(self, command: list[str], *, include_stderr: bool = False) -> str:
        try:
            result = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                timeout=self.timeout,
                check=False,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise VideoCompositionEnhancementProbeError(
                "ENHANCEMENT_QA_FAILED"
            ) from exc
        output = result.stderr if include_stderr else result.stdout
        if (
            result.returncode
            or len(result.stdout) + len(result.stderr) > self.MAX_OUTPUT
        ):
            raise VideoCompositionEnhancementProbeError("ENHANCEMENT_QA_FAILED")
        return output
