"""Low-bitrate authenticated previews; source artifacts remain immutable."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path
from threading import BoundedSemaphore, Lock

from app.core.exceptions import AppError

PREVIEW_VERSION = "v1-720p-1200k"
_LOCKS = [Lock() for _ in range(32)]
_ENCODERS = BoundedSemaphore(1)


def video_preview_path(source: Path, digest: str, ffmpeg: str) -> Path:
    folder = source.parent / ".previews"
    target = folder / f"{digest}-{PREVIEW_VERSION}.mp4"
    lock_index = hashlib.sha256(str(target).encode()).digest()[0] % len(_LOCKS)
    with _LOCKS[lock_index]:
        if target.is_file() and target.stat().st_size > 0:
            return target
        folder.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=folder, suffix=".mp4", delete=False
        ) as tmp:
            temporary = Path(tmp.name)
        try:
            with _ENCODERS:
                result = subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-threads",
                        "1",
                        "-i",
                        str(source),
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a:0?",
                        "-map_metadata",
                        "-1",
                        "-vf",
                        "scale='trunc(min(720,iw)/2)*2':-2,fps=24",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-profile:v",
                        "high",
                        "-pix_fmt",
                        "yuv420p",
                        "-crf",
                        "30",
                        "-maxrate",
                        "1200k",
                        "-bufsize",
                        "2400k",
                        "-g",
                        "48",
                        "-keyint_min",
                        "24",
                        "-sc_threshold",
                        "0",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "64k",
                        "-ar",
                        "44100",
                        "-ac",
                        "2",
                        "-movflags",
                        "+faststart",
                        "-threads",
                        "1",
                        "-y",
                        str(temporary),
                    ],
                    capture_output=True,
                    check=False,
                    timeout=120,
                )
            if (
                result.returncode
                or not temporary.is_file()
                or not temporary.stat().st_size
            ):
                raise AppError("Video preview could not be generated", 503)
            temporary.replace(target)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AppError("Video preview is temporarily unavailable", 503) from exc
        finally:
            temporary.unlink(missing_ok=True)
    return target
