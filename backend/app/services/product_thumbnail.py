"""Small authenticated previews; originals remain immutable generation inputs."""

import hashlib
import subprocess
import tempfile
from pathlib import Path
from threading import BoundedSemaphore, Lock

from app.core.exceptions import AppError

_LOCKS = [Lock() for _ in range(32)]
_ENCODERS = BoundedSemaphore(2)
THUMBNAIL_VERSION = "v1-320"


def thumbnail_path(source: Path, digest: str, ffmpeg: str) -> Path:
    folder = source.parent / ".thumbnails"
    target = folder / f"{digest}-{THUMBNAIL_VERSION}.webp"
    lock_index = hashlib.sha256(str(target).encode()).digest()[0] % len(_LOCKS)
    with _LOCKS[lock_index]:
        if target.is_file() and target.stat().st_size > 0:
            return target
        folder.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=folder, suffix=".webp", delete=False
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
                        "-map_metadata",
                        "-1",
                        "-vf",
                        "scale=320:320:force_original_aspect_ratio=decrease",
                        "-frames:v",
                        "1",
                        "-c:v",
                        "libwebp",
                        "-quality",
                        "75",
                        "-threads",
                        "1",
                        "-y",
                        str(temporary),
                    ],
                    capture_output=True,
                    check=False,
                    timeout=20,
                )
            if (
                result.returncode
                or not temporary.is_file()
                or not temporary.stat().st_size
            ):
                raise AppError("Product preview could not be generated", 503)
            temporary.replace(target)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AppError("Product preview is temporarily unavailable", 503) from exc
        finally:
            temporary.unlink(missing_ok=True)
    return target
