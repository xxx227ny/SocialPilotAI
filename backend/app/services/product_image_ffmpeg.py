from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import AppError


class ProductImageFfmpeg:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def render(self, image: Path, duration_seconds: int, motion: str) -> bytes:
        frames = duration_seconds * 30
        zoom = {
            "zoom_in": "min(zoom+0.0008,1.08)",
            "zoom_out": "if(eq(on,1),1.08,max(zoom-0.0008,1.0))",
            "pan_left": "1.04",
            "pan_right": "1.04",
        }[motion]
        x = {
            "zoom_in": "iw/2-(iw/zoom/2)",
            "zoom_out": "iw/2-(iw/zoom/2)",
            "pan_left": f"(iw-iw/zoom)*(1-on/{frames})",
            "pan_right": f"(iw-iw/zoom)*(on/{frames})",
        }[motion]
        filters = (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,setsar=1,"
            f"zoompan=z='{zoom}':x='{x}':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s=1080x1920:fps=30,format=yuv420p"
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "shot.mp4"
            command = [
                self.settings.video_composition_ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-loop",
                "1",
                "-i",
                str(image),
                "-vf",
                filters,
                "-t",
                str(duration_seconds),
                "-an",
                "-c:v",
                "libx264",
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                "-movflags",
                "+faststart",
                "-y",
                str(output),
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    timeout=self.settings.video_composition_process_timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise AppError("Product image rendering failed", 500) from exc
            if completed.returncode != 0 or not output.is_file():
                raise AppError("Product image rendering failed", 500)
            return output.read_bytes()
