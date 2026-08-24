from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.core.exceptions import AppError
from app.providers.visual_base import VisualReferenceImage

HAPPYHORSE_REFERENCE_MEDIA_CONTRACT = "jpeg-720x1280-fit-pad-v1"
HAPPYHORSE_REFERENCE_MAX_BYTES = 500_000
HAPPYHORSE_REFERENCE_TOTAL_MAX_BYTES = 4_500_000

_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
_JPEG_QUALITIES = (8, 12, 18, 24)


class HappyHorseReferenceMedia:
    """Create bounded, deterministic provider references from frozen assets."""

    def __init__(self, ffmpeg_path: str, timeout: float) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.timeout = timeout

    def normalize(self, content: bytes, content_type: str) -> VisualReferenceImage:
        extension = _EXTENSIONS.get(content_type)
        if not content or extension is None:
            raise AppError("HappyHorse reference image format is invalid", 409)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / f"source.{extension}"
            source.write_bytes(content)
            for quality in _JPEG_QUALITIES:
                output = root / f"reference-q{quality}.jpg"
                self._convert(source, output, quality)
                payload = output.read_bytes() if output.is_file() else b""
                if (
                    payload.startswith(b"\xff\xd8\xff")
                    and len(payload) <= HAPPYHORSE_REFERENCE_MAX_BYTES
                ):
                    return VisualReferenceImage(payload, "image/jpeg")
        raise AppError("HappyHorse reference image cannot meet payload limit", 422)

    def _convert(self, source: Path, output: Path, quality: int) -> None:
        try:
            result = subprocess.run(
                [
                    self.ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-i",
                    str(source),
                    "-map_metadata",
                    "-1",
                    "-vf",
                    (
                        "scale=720:1280:force_original_aspect_ratio=decrease,"
                        "pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1"
                    ),
                    "-frames:v",
                    "1",
                    "-c:v",
                    "mjpeg",
                    "-q:v",
                    str(quality),
                    "-pix_fmt",
                    "yuvj420p",
                    "-y",
                    str(output),
                ],
                capture_output=True,
                check=False,
                timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AppError(
                "HappyHorse reference image converter is unavailable", 503
            ) from exc
        if result.returncode != 0 or not output.is_file():
            raise AppError("HappyHorse reference image conversion failed", 422)
