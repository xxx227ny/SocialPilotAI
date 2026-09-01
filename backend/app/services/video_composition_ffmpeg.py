from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class VideoCompositionFFmpegError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FFmpegShot:
    path: Path
    trim_start_ms: int
    duration_ms: int


class VideoCompositionFFmpeg:
    MAX_DIAGNOSTIC_BYTES = 64 * 1024

    def __init__(self, executable: str, timeout: float) -> None:
        self.executable = executable
        self.timeout = timeout

    def render(self, shots: list[FFmpegShot], output: Path) -> None:
        if not shots:
            raise VideoCompositionFFmpegError("COMPOSITION_SHOTS_INVALID")
        command = [
            self.executable,
            "-y",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
        ]
        filters: list[str] = []
        for index, shot in enumerate(shots):
            if not shot.path.is_absolute() or not shot.path.is_file():
                raise VideoCompositionFFmpegError("COMPOSITION_SOURCE_UNAVAILABLE")
            command.extend(
                [
                    "-ss",
                    f"{shot.trim_start_ms / 1000:.3f}",
                    "-t",
                    f"{shot.duration_ms / 1000:.3f}",
                    "-i",
                    str(shot.path),
                ]
            )
            filters.append(
                f"[{index}:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p,"
                f"setpts=PTS-STARTPTS[v{index}]"
            )
        command.extend(["-f", "lavfi", "-t", "15", "-i", "anullsrc=r=48000:cl=stereo"])
        concat_inputs = "".join(f"[v{index}]" for index in range(len(shots)))
        filter_graph = ";".join(
            filters + [f"{concat_inputs}concat=n={len(shots)}:v=1:a=0[vout]"]
        )
        command.extend(
            [
                "-filter_complex",
                filter_graph,
                "-map",
                "[vout]",
                "-map",
                f"{len(shots)}:a",
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
        try:
            result = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise VideoCompositionFFmpegError("COMPOSITION_FFMPEG_FAILED") from exc
        if (
            result.returncode
            or len(result.stdout) > self.MAX_DIAGNOSTIC_BYTES
            or len(result.stderr) > self.MAX_DIAGNOSTIC_BYTES
            or not output.is_file()
        ):
            raise VideoCompositionFFmpegError("COMPOSITION_FFMPEG_FAILED")
