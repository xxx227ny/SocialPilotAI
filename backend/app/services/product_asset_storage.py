from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import AppError

FORMATS: dict[str, tuple[set[str], str]] = {
    "jpeg": ({"jpg", "jpeg"}, "image/jpeg"),
    "png": ({"png"}, "image/png"),
    "webp": ({"webp"}, "image/webp"),
}


@dataclass(frozen=True)
class StoredProductImage:
    storage_identity: str
    path: Path
    content: bytes
    extension: str
    content_type: str
    sha256: str
    width: int
    height: int


class ProductAssetStorage:
    def __init__(
        self,
        root: Path,
        max_bytes: int,
        *,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
        process_timeout: float = 60,
    ) -> None:
        if not root.is_absolute():
            raise AppError("Product asset storage is not configured", 503)
        self.root = root.resolve()
        self.max_bytes = max_bytes
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.process_timeout = process_timeout

    def normalize(
        self, file_name: str, declared_type: str, content: bytes
    ) -> StoredProductImage:
        if not content or len(content) > self.max_bytes:
            raise AppError("Product image size is invalid", 422)
        detected = self._magic_type(content)
        allowed_extensions, expected_type = FORMATS[detected]
        source_extension = Path(file_name).suffix.lower().removeprefix(".")
        if source_extension not in allowed_extensions:
            raise AppError("Product image extension does not match content", 422)
        if declared_type.split(";", 1)[0].strip().lower() != expected_type:
            raise AppError("Product image MIME does not match content", 422)
        payload, width, height = self._decode_and_normalize(content, source_extension)
        if len(payload) > self.max_bytes:
            raise AppError("Normalized product image exceeds the size limit", 422)
        extension, content_type = "png", "image/png"
        digest = hashlib.sha256(payload).hexdigest()
        identity = f"product-images/{digest[:2]}/{digest}.{extension}"
        path = (self.root / identity).resolve()
        if self.root not in path.parents:
            raise AppError("Product image path is unsafe", 422)
        return StoredProductImage(
            identity, path, payload, extension, content_type, digest, width, height
        )

    @staticmethod
    def _magic_type(content: bytes) -> str:
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
        if content.startswith(b"\xff\xd8\xff"):
            return "jpeg"
        if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "webp"
        raise AppError("Unsupported product image magic", 422)

    def _decode_and_normalize(
        self, content: bytes, source_extension: str
    ) -> tuple[bytes, int, int]:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / f"source.{source_extension}"
            output = Path(temporary) / "normalized.png"
            source.write_bytes(content)
            try:
                decoded = subprocess.run(
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
                        "-frames:v",
                        "1",
                        "-y",
                        str(output),
                    ],
                    capture_output=True,
                    check=False,
                    timeout=self.process_timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise AppError("Product image decoder is unavailable", 503) from exc
            if decoded.returncode != 0 or not output.is_file():
                raise AppError("Product image cannot be decoded", 422)
            try:
                probe = subprocess.run(
                    [
                        self.ffprobe_path,
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_entries",
                        "stream=width,height,codec_name",
                        "-of",
                        "json",
                        str(output),
                    ],
                    capture_output=True,
                    check=False,
                    timeout=self.process_timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise AppError("Product image probe is unavailable", 503) from exc
            if probe.returncode != 0:
                raise AppError("Normalized product image cannot be probed", 422)
            try:
                stream = json.loads(probe.stdout)["streams"][0]
                width, height = int(stream["width"]), int(stream["height"])
            except (
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                raise AppError("Product image dimensions are unavailable", 422) from exc
            if not (64 <= width <= 12000 and 64 <= height <= 12000):
                raise AppError("Product image dimensions are invalid", 422)
            return output.read_bytes(), width, height

    def persist(self, image: StoredProductImage) -> bool:
        image.path.parent.mkdir(parents=True, exist_ok=True)
        if image.path.exists():
            if hashlib.sha256(image.path.read_bytes()).hexdigest() != image.sha256:
                raise AppError("Immutable product image mismatch", 409)
            return False
        temporary = image.path.with_suffix(f"{image.path.suffix}.tmp")
        temporary.write_bytes(image.content)
        temporary.replace(image.path)
        return True

    def resolve(self, identity: str, sha256: str) -> Path:
        path = (self.root / identity).resolve()
        if self.root not in path.parents or not path.is_file():
            raise AppError("Product asset not found", 404)
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            raise AppError("Product asset digest mismatch", 409)
        return path
