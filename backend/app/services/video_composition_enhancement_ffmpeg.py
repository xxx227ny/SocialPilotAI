from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.services.video_composition_subtitles import render_ass_from_webvtt


class VideoCompositionEnhancementFFmpegError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EnhancementFFmpegInput:
    video: Path
    voiceover: Path
    music: Path | None
    subtitle: Path
    voiceover_gain_millidb: int
    music_gain_millidb: int
    ducking_reduction_millidb: int
    target_lufs_milli: int
    true_peak_millidb: int
    font_size: int
    bottom_margin: int
    outline_width: int
    voiceover_natural_duration_ms: int | None = None


class VideoCompositionEnhancementFFmpeg:
    MAX_DIAGNOSTIC_BYTES = 64 * 1024

    def __init__(self, executable: str, timeout: float) -> None:
        self.executable = executable
        self.timeout = timeout

    def render(self, data: EnhancementFFmpegInput, output: Path) -> None:
        for path in (data.video, data.voiceover, data.subtitle):
            if not path.is_absolute() or not path.is_file():
                raise VideoCompositionEnhancementFFmpegError(
                    "ENHANCEMENT_SOURCE_UNAVAILABLE"
                )
        if data.music is not None and (
            not data.music.is_absolute() or not data.music.is_file()
        ):
            raise VideoCompositionEnhancementFFmpegError(
                "ENHANCEMENT_SOURCE_UNAVAILABLE"
            )
        command = [
            self.executable,
            "-y",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(data.video),
            "-i",
            str(data.voiceover),
        ]
        if data.music is not None:
            command.extend(["-stream_loop", "-1", "-i", str(data.music)])
        voice_gain = data.voiceover_gain_millidb / 1000
        music_gain = data.music_gain_millidb / 1000
        target_lufs = data.target_lufs_milli / 1000
        true_peak = data.true_peak_millidb / 1000
        ratio = max(2.0, min(20.0, data.ducking_reduction_millidb / 1500))
        voice_timing = self._voice_timing_filter(data.voiceover_natural_duration_ms)
        voice_output = "voice_source" if data.music is not None else "voice"
        audio_filters = (
            f"[1:a]aresample=48000,aformat=sample_fmts=fltp:"
            f"channel_layouts=stereo,{voice_timing}volume={voice_gain:.3f}dB,"
            f"apad,atrim=0:15[{voice_output}]"
        )
        if data.music is not None:
            audio_filters += (
                ";[voice_source]asplit=2[voice][voice_sidechain];"
                f"[2:a]aresample=48000,aformat=sample_fmts=fltp:"
                f"channel_layouts=stereo,volume={music_gain:.3f}dB,"
                "atrim=0:15[music];"
                f"[music][voice_sidechain]sidechaincompress="
                f"threshold=0.02:ratio={ratio:.3f}:"
                "attack=20:release=300[ducked];"
                "[voice][ducked]amix=inputs=2:duration=longest:normalize=0[mix]"
            )
        else:
            audio_filters += ";[voice]anull[mix]"
        limit = 10 ** (true_peak / 20)
        measured_lufs, measured_true_peak = self._measure_mix(
            data,
            audio_filters,
            target_lufs,
            true_peak,
        )
        # Normalize integrated loudness first. The limiter below is the authority
        # for peak protection; capping this gain by the source peak leaves
        # high-crest-factor speech materially quieter than the frozen target.
        fixed_gain = target_lufs - measured_lufs
        audio_filters += (
            f";[mix]volume={fixed_gain:.3f}dB,"
            f"alimiter=limit={limit:.6f}:level=false[aout]"
        )
        try:
            burn_subtitle = data.subtitle.with_suffix(".ass")
            burn_subtitle.write_bytes(
                render_ass_from_webvtt(
                    data.subtitle.read_bytes(),
                    font_size=data.font_size,
                    bottom_margin=data.bottom_margin,
                    outline_width=data.outline_width,
                )
            )
        except (OSError, ValueError) as exc:
            raise VideoCompositionEnhancementFFmpegError(
                "ENHANCEMENT_SUBTITLE_INVALID"
            ) from exc
        subtitle_name = burn_subtitle.name.replace("'", "")
        video_filter = (
            f"[0:v]subtitles=filename='{subtitle_name}':original_size=1080x1920[vout]"
        )
        command.extend(
            [
                "-filter_complex",
                f"{video_filter};{audio_filters}",
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-t",
                "15",
                "-c:v",
                "libx264",
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                "-fps_mode",
                "cfr",
                "-g",
                "60",
                "-keyint_min",
                "30",
                "-sc_threshold",
                "0",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(output),
            ]
        )
        if not all(math.isfinite(value) for value in (limit, fixed_gain)):
            raise VideoCompositionEnhancementFFmpegError(
                "ENHANCEMENT_PARAMETERS_INVALID"
            )
        try:
            result = subprocess.run(
                command,
                cwd=data.subtitle.parent,
                shell=False,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise VideoCompositionEnhancementFFmpegError(
                "ENHANCEMENT_FFMPEG_FAILED"
            ) from exc
        if (
            result.returncode
            or len(result.stdout) > self.MAX_DIAGNOSTIC_BYTES
            or len(result.stderr) > self.MAX_DIAGNOSTIC_BYTES
            or not output.is_file()
        ):
            raise VideoCompositionEnhancementFFmpegError("ENHANCEMENT_FFMPEG_FAILED")

    def _measure_mix(
        self,
        data: EnhancementFFmpegInput,
        audio_filters: str,
        target_lufs: float,
        true_peak: float,
    ) -> tuple[float, float]:
        command = [
            self.executable,
            "-nostdin",
            "-v",
            "info",
            "-i",
            str(data.video),
            "-i",
            str(data.voiceover),
        ]
        if data.music is not None:
            command.extend(["-stream_loop", "-1", "-i", str(data.music)])
        command.extend(
            [
                "-filter_complex",
                (
                    f"{audio_filters};[mix]loudnorm=I={target_lufs:.3f}:"
                    f"TP={true_peak:.3f}:LRA=11:print_format=json[measure]"
                ),
                "-map",
                "[measure]",
                "-f",
                "null",
                "-",
            ]
        )
        try:
            result = subprocess.run(
                command,
                cwd=data.subtitle.parent,
                shell=False,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise VideoCompositionEnhancementFFmpegError(
                "ENHANCEMENT_LOUDNESS_ANALYSIS_FAILED"
            ) from exc
        if (
            result.returncode
            or len(result.stdout) > self.MAX_DIAGNOSTIC_BYTES
            or len(result.stderr) > self.MAX_DIAGNOSTIC_BYTES
        ):
            raise VideoCompositionEnhancementFFmpegError(
                "ENHANCEMENT_LOUDNESS_ANALYSIS_FAILED"
            )
        try:
            stderr = result.stderr.decode("utf-8", errors="strict")
            blocks = re.findall(r'\{\s*"input_i".*?\}', stderr, re.DOTALL)
            payload = json.loads(blocks[-1])
            measured_lufs = float(payload["input_i"])
            measured_true_peak = float(payload["input_tp"])
        except (
            UnicodeDecodeError,
            IndexError,
            KeyError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise VideoCompositionEnhancementFFmpegError(
                "ENHANCEMENT_LOUDNESS_ANALYSIS_FAILED"
            ) from None
        measured_values = (measured_lufs, measured_true_peak)
        if not all(math.isfinite(value) for value in measured_values):
            raise VideoCompositionEnhancementFFmpegError(
                "ENHANCEMENT_LOUDNESS_ANALYSIS_FAILED"
            )
        return measured_lufs, measured_true_peak

    @staticmethod
    def _voice_timing_filter(natural_duration_ms: int | None) -> str:
        """Fit short speech to 14 seconds while preserving pitch with atempo."""
        target_ms = 14_000
        if natural_duration_ms is None or natural_duration_ms >= target_ms:
            return ""
        if natural_duration_ms <= 0:
            raise VideoCompositionEnhancementFFmpegError(
                "ENHANCEMENT_PARAMETERS_INVALID"
            )
        ratio = natural_duration_ms / target_ms
        factors: list[float] = []
        while ratio < 0.5:
            factors.append(0.5)
            ratio /= 0.5
        factors.append(ratio)
        chain = ",".join(f"atempo={factor:.6f}" for factor in factors)
        natural_seconds = natural_duration_ms / 1000
        return f"atrim=0:{natural_seconds:.3f},{chain},"
